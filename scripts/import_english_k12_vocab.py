import argparse
import os
import sys
import uuid
import hashlib
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy.dialects.postgresql import insert

from services.models import VocabularyItem, VocabularyCollection, VocabularyCollectionMembership, VocabularyImportBatch
from obase.db import SessionLocal

from scripts.vocab_importer.metadata import parse_metadata
from scripts.vocab_importer.schema_detector import detect_schema
from scripts.vocab_importer.parser import parse_workbook
from scripts.vocab_importer.normalizer import normalize_term, get_lexeme_type

def get_file_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def get_vid(normalized_form: str) -> str:
    # uuid5(MNEME_ENGLISH_VOCAB_NAMESPACE, "en:" + normalized_form)
    MNEME_ENGLISH_VOCAB_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8") # standard DNS namespace as placeholder
    return str(uuid.uuid5(MNEME_ENGLISH_VOCAB_NAMESPACE, "en:" + normalized_form))

async def run_discovery(source_root: str, scopes: list) -> dict:
    inventory = {"k12_sync": [], "zhongkao": [], "gaokao": []}
    for root, dirs, files in os.walk(source_root):
        rel_path = os.path.relpath(root, source_root)
        if any(x in rel_path for x in ["考研", "四级", "六级", "雅思", "托福", "GRE", "SAT", "专四", "专八", "大学", "商务英语", "国际英语", "新概念英语"]):
            continue
        scope_match = None
        if "1.全国各大教材版本中小学同步" in rel_path and "k12-sync" in scopes: scope_match = "k12_sync"
        elif "中考" in rel_path and "zhongkao" in scopes: scope_match = "zhongkao"
        elif "高考" in rel_path and "gaokao" in scopes: scope_match = "gaokao"
            
        if scope_match:
            for f in files:
                if f.endswith(".xlsx") and not f.startswith("~"):
                    inventory[scope_match].append(os.path.join(root, f))
    return inventory

async def main_async():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--scope", default="k12-sync,zhongkao,gaokao")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    
    args = parser.parse_args()
    scopes = args.scope.split(",")
    inventory = await run_discovery(args.source_root, scopes)
    
    total_files = sum(len(v) for v in inventory.values())
    print(f"Found {total_files} workbooks.")
    
    report = {
        "FILES_TOTAL": total_files,
        "FILES_PARSED": 0,
        "FILES_FAILED": 0,
        "SCHEMA_HEADERLESS": 0,
        "UNKNOWN_SCHEMA": 0,
        "ROWS_TOTAL": 0,
        "ROWS_VALID": 0,
        "WORD_COUNT": 0,
        "PHRASE_COUNT": 0,
        "UNKNOWN_SCHEMA_FILES": []
    }
    
    for scope, files in inventory.items():
        for f in files:
            schema, header = detect_schema(f)
            if schema == "UNKNOWN_SCHEMA" or schema == "FATAL_PARSE_ERROR":
                report["UNKNOWN_SCHEMA"] += 1
                report["FILES_FAILED"] += 1
                report["UNKNOWN_SCHEMA_FILES"].append(f)
            else:
                if schema == "SCHEMA_HEADERLESS": report["SCHEMA_HEADERLESS"] += 1
                report["FILES_PARSED"] += 1
                
                # Dry run parse
                entries = list(parse_workbook(f, schema))
                report["ROWS_TOTAL"] += len(entries)
                report["ROWS_VALID"] += len(entries)
                for e in entries:
                    norm = normalize_term(e.term)
                    if get_lexeme_type(norm) == "WORD":
                        report["WORD_COUNT"] += 1
                    else:
                        report["PHRASE_COUNT"] += 1

    print("\n=== DRY RUN REPORT ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    
    if args.dry_run:
        print("Dry run complete.")
        return

    if args.apply:
        batch_id = str(uuid.uuid4())
        async with SessionLocal() as db:
            batch = VocabularyImportBatch(
                id=batch_id,
                source_name="lilinji-English",
                source_commit_sha="6996d60339f21501efb7796a959165e083b5a7f5",
                mode="APPLY",
                status="RUNNING"
            )
            db.add(batch)
            await db.commit()
            
            vocab_created = 0
            collections_created = 0
            memberships_created = 0
            
            for scope, files in inventory.items():
                for f in files:
                    schema, header = detect_schema(f)
                    if schema in ["UNKNOWN_SCHEMA", "FATAL_PARSE_ERROR"]:
                        continue
                        
                    rel_path = os.path.relpath(f, args.source_root)
                    meta = parse_metadata(rel_path, os.path.basename(f))
                    meta.source_file_sha256 = get_file_sha256(f)
                    
                    collection_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mneme://collection/{rel_path}"))
                    
                    # Upsert Collection
                    stmt_coll = insert(VocabularyCollection).values(
                        id=collection_id,
                        kind=meta.kind,
                        scope=meta.scope,
                        title=meta.title,
                        publisher=meta.publisher,
                        stage=meta.stage,
                        grade=meta.grade,
                        semester=meta.semester,
                        book_type=meta.book_type,
                        exam_type=meta.exam_type,
                        source_relative_path=meta.source_relative_path,
                        source_file_sha256=meta.source_file_sha256
                    ).on_conflict_do_nothing(index_elements=['id'])
                    await db.execute(stmt_coll)
                    collections_created += 1
                    
                    entries = list(parse_workbook(f, schema))
                    for e in entries:
                        norm = normalize_term(e.term)
                        vid = get_vid(norm)
                        lex_type = get_lexeme_type(norm)
                        
                        stmt_vocab = insert(VocabularyItem).values(
                            id=vid,
                            word=e.term,
                            language="en",
                            display_form=e.term,
                            normalized_form=norm,
                            lexeme_type=lex_type,
                            canonical_meaning=e.definition_raw,
                            frequency_rank=99999,
                            frequency_band=5,
                            source="k12_sync"
                        ).on_conflict_do_nothing(index_elements=['id'])
                        await db.execute(stmt_vocab)
                        vocab_created += 1
                        
                        mem_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mneme://membership/{collection_id}/{vid}"))
                        stmt_mem = insert(VocabularyCollectionMembership).values(
                            id=mem_id,
                            collection_id=collection_id,
                            vocabulary_item_id=vid,
                            source_order=e.source_order,
                            source_definition=e.definition_raw,
                            source_relative_path=meta.source_relative_path,
                            source_row=e.source_row
                        ).on_conflict_do_nothing(constraint='uq_vocab_membership')
                        await db.execute(stmt_mem)
                        memberships_created += 1
            
            batch.status = "SUCCESS"
            batch.vocab_created = vocab_created
            batch.collections_created = collections_created
            batch.memberships_created = memberships_created
            await db.commit()
            print("Apply complete.")

if __name__ == "__main__":
    asyncio.run(main_async())
