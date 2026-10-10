from .models import VocabularyCollectionMeta

PUBLISHER_MAP = {
    "人教版": "PEP",
    "外研版": "FLTRP",
    "北师大版": "BNU",
    "译林版": "YILIN",
    "冀教版": "HEBEI",
    "仁爱版": "RENAI",
    "剑桥版": "CAMBRIDGE",
    "北京版": "BEIJING",
    "广东版": "GUANGDONG",
    "广州版": "GUANGZHOU",
    "教科版": "JIAOKEO",
    "沪教版": "HUJIAO",
    "鲁科版": "LUKE",
    "科普版": "KEPU",
    "湘少版": "XIANGSHAO",
    "重大版": "CHONGQING",
    "川教版": "CHUANJIAO",
    "陕旅版": "SHANLV"
}

def parse_metadata(relative_path: str, file_name: str) -> VocabularyCollectionMeta:
    # 默认值
    kind = "TEXTBOOK"
    scope = "K12_SYNC"
    stage = "UNKNOWN"
    publisher = None
    grade = None
    semester = None
    edition = None
    curriculum_year = None
    book_type = None
    exam_type = None
    region = None
    
    if "中考" in relative_path or "中考" in file_name:
        kind = "EXAM"
        scope = "ZHONGKAO"
        exam_type = "ZHONGKAO"
        stage = "JUNIOR"
    elif "高考" in relative_path or "高考" in file_name:
        kind = "EXAM"
        scope = "GAOKAO"
        exam_type = "GAOKAO"
        stage = "SENIOR"
    else:
        # 教材推断
        for p_cn, p_code in PUBLISHER_MAP.items():
            if p_cn in relative_path or p_cn in file_name:
                publisher = p_code
                break
        
        if not publisher:
            publisher = "UNKNOWN"
            
        grade_str = ""
        # 提取年级
        grades = {"一年级": 1, "二年级": 2, "三年级": 3, "四年级": 4, "五年级": 5, "六年级": 6, "七年级": 7, "八年级": 8, "九年级": 9}
        for g_cn, g_num in grades.items():
            if g_cn in file_name or g_cn in relative_path:
                grade = g_num
                break
                
        # 提取册次
        if "上册" in file_name or "上" in file_name:
            semester = 1
        elif "下册" in file_name or "下" in file_name:
            semester = 2
            
        # 提取学段
        if "小学" in relative_path or "小学" in file_name or (grade and grade <= 6):
            stage = "PRIMARY"
        elif "初中" in relative_path or "初中" in file_name or (grade and 7 <= grade <= 9):
            stage = "JUNIOR"
        elif "高中" in relative_path or "高中" in file_name or (grade and grade >= 10):
            stage = "SENIOR"
            
        # 提取 book_type
        if "选择性必修" in file_name:
            book_type = "SELECTIVE_COMPULSORY"
        elif "必修" in file_name:
            book_type = "COMPULSORY"
        elif "选修" in file_name:
            book_type = "ELECTIVE"

    return VocabularyCollectionMeta(
        kind=kind,
        scope=scope,
        title=file_name.replace(".xlsx", ""),
        publisher=publisher,
        stage=stage,
        grade=grade,
        semester=semester,
        edition=edition,
        curriculum_year=curriculum_year,
        book_type=book_type,
        exam_type=exam_type,
        region=region,
        source_relative_path=relative_path,
        source_file_sha256="" # Will be filled later
    )
