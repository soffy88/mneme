import pytest
import base64
from oprim.llm_oprims import ocr_paper, PaperOCRResult
from obase.provider_registry import ProviderRegistry


class _FakeVLM:
    async def __call__(self, **kwargs):
        return {"content": {"questions": []}, "raw_text": "Mock VLM Response"}


class _FakeRegistry:
    def __init__(self):
        self._vlm = _FakeVLM()

    def vlm(self):
        return self._vlm

@pytest.fixture(autouse=True)
def setup_mock_llm(monkeypatch):
    # Register the mock at the provider boundary this oprim actually uses.
    # obase.llm's legacy mock registry does not replace services.providers.
    registry = _FakeRegistry()
    monkeypatch.setattr(
        ProviderRegistry, "get", classmethod(lambda cls: registry)
    )

@pytest.mark.asyncio
async def test_ocr_paper_mock():
    # 模拟一个小的 base64 图片字符串
    fake_image_b64 = base64.b64encode(b"fake image data").decode()
    
    result = await ocr_paper(image_b64=fake_image_b64)
    
    assert isinstance(result, PaperOCRResult)
    # 因为是用 mock provider，默认返回空列表
    assert isinstance(result.questions, list)
    assert result.raw_text == "Mock VLM Response"
