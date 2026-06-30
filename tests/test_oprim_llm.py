import pytest
import base64
from oprim.llm_oprims import ocr_paper, PaperOCRResult
from obase.llm import register_mock_providers

@pytest.fixture(autouse=True)
def setup_mock_llm():
    try:
        register_mock_providers()
    except Exception:
        pass  # 同一 pytest 进程已注册即可复用

@pytest.mark.asyncio
async def test_ocr_paper_mock():
    # 模拟一个小的 base64 图片字符串
    fake_image_b64 = base64.b64encode(b"fake image data").decode()
    
    result = await ocr_paper(image_b64=fake_image_b64)
    
    assert isinstance(result, PaperOCRResult)
    # 因为是用 mock provider，默认返回空列表
    assert isinstance(result.questions, list)
    assert result.raw_text == "Mock VLM Response"
