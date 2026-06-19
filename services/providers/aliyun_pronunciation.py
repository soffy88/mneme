import base64
import time
import uuid
import hmac
import hashlib
import urllib.parse
import json
import logging
import asyncio
import httpx
import websockets
from typing import Optional
from oprim._mneme_speech_types import PronunciationResult

logger = logging.getLogger(__name__)

class AliyunPronunciationCaller:
    """阿里云语音评测 (Intelligent Speech Evaluation) Provider.
    
    需要：
    - access_key_id
    - access_key_secret
    - app_key
    """
    def __init__(self, access_key_id: str, access_key_secret: str, app_key: Optional[str] = None):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.app_key = app_key or ""

    def get_token_url(self) -> str:
        """从阿里云 NLS Meta 节点生成临时 Token。"""
        params = {
            "AccessKeyId": self.access_key_id,
            "Action": "CreateToken",
            "Format": "JSON",
            "RegionId": "cn-shanghai",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Version": "2019-02-28",
        }
        
        sorted_params = sorted(params.items())
        canonicalized_query_string = urllib.parse.urlencode(sorted_params)
        string_to_sign = "GET&%2F&" + urllib.parse.quote(canonicalized_query_string, safe='')
        
        key = (self.access_key_secret + "&").encode('utf-8')
        signature = base64.b64encode(
            hmac.new(key, string_to_sign.encode('utf-8'), hashlib.sha1).digest()
        ).decode('utf-8')
        
        params["Signature"] = signature
        url = "http://nls-meta.cn-shanghai.aliyuncs.com/v1/token?" + urllib.parse.urlencode(params)
        return url

    async def fetch_token(self) -> str:
        url = self.get_token_url()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data["Token"]["Id"]

    async def __call__(
        self,
        *,
        audio_b64: str,
        reference_text: str,
        **kwargs
    ) -> PronunciationResult:
        if not reference_text:
            raise ValueError("reference_text must not be empty")
        if not audio_b64:
            raise ValueError("audio_b64 must not be empty")

        token = await self.fetch_token()
        ws_url = f"wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1?token={token}"
        
        # 16kHz, 16bit, 单声道 PCM 数据
        audio_bytes = base64.b64decode(audio_b64)
        
        task_id = uuid.uuid4().hex
        
        start_message = {
            "header": {
                "message_id": uuid.uuid4().hex,
                "task_id": task_id,
                "namespace": "SpeechEvaluator",
                "name": "Start",
                "appkey": self.app_key
            },
            "payload": {
                "format": "pcm",
                "sample_rate": 16000,
                "eval_accent": "english",
                "eval_mode": "sentence",
                "text": reference_text
            }
        }
        
        stop_message = {
            "header": {
                "message_id": uuid.uuid4().hex,
                "task_id": task_id,
                "namespace": "SpeechEvaluator",
                "name": "Stop",
                "appkey": self.app_key
            }
        }

        async with websockets.connect(ws_url) as ws:
            # Send Start
            await ws.send(json.dumps(start_message))
            
            # Wait for Started
            started = False
            async for msg in ws:
                resp = json.loads(msg)
                name = resp.get("header", {}).get("name")
                if name == "Started":
                    started = True
                    break
                elif name == "TaskFailed":
                    raise RuntimeError(f"Aliyun SpeechEvaluator TaskFailed: {resp}")
            
            if not started:
                raise RuntimeError("Failed to start Aliyun SpeechEvaluator session")
                
            # Send Audio chunks
            chunk_size = 3200
            for i in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[i:i+chunk_size]
                await ws.send(chunk)
                await asyncio.sleep(0.01)
                
            # Send Stop
            await ws.send(json.dumps(stop_message))
            
            # Read response
            result_payload = {}
            async for msg in ws:
                resp = json.loads(msg)
                header = resp.get("header", {})
                name = header.get("name")
                if name in ("EvaluationResult", "Completed"):
                    result_payload = resp.get("payload", {})
                if name == "Completed":
                    break
                elif name == "TaskFailed":
                    raise RuntimeError(f"Aliyun SpeechEvaluator TaskFailed: {resp}")
                    
            pron = result_payload.get("result", {}).get("pronunciation", {})
            raw_overall = pron.get("overall", pron.get("overall_score", 0.0))
            raw_fluency = pron.get("fluency", pron.get("fluency_score", 0.0))
            raw_accuracy = pron.get("accuracy", pron.get("accuracy_score", 0.0))
            
            def normalize_score(s):
                try:
                    val = float(s)
                except (TypeError, ValueError):
                    val = 0.0
                if val > 5.0:
                    return min(val / 100.0, 1.0)
                else:
                    return min(val / 5.0, 1.0)
                    
            word_scores = []
            for w in result_payload.get("result", {}).get("words", []):
                word_scores.append({
                    "word": w.get("word", ""),
                    "score": normalize_score(w.get("score", 0.0)),
                    "issue": w.get("pronunciation", {}).get("issue", "")
                })

            return PronunciationResult(
                overall_score=normalize_score(raw_overall),
                fluency_score=normalize_score(raw_fluency),
                accuracy_score=normalize_score(raw_accuracy),
                word_scores=word_scores
            )
