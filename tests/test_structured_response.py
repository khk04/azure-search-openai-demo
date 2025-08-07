import json
import pytest
from unittest import mock
from openai.types.chat import ChatCompletion, ChatCompletionMessage, Choice
from openai.types import CompletionUsage


@pytest.mark.asyncio
async def test_ask_structured_json_response(client, snapshot):
    """JSON 형식으로 summary + chart_data를 포함한 구조화된 응답 테스트"""
    response = await client.post(
        "/ask",
        json={
            "messages": [{"content": "2023년 매출 현황을 분석해줘", "role": "user"}],
            "context": {
                "overrides": {"structured_response": True},
            },
        },
    )
    
    assert response.status_code == 200
    result = await response.get_json()
    
    # 기본 응답 구조 검증
    assert "message" in result
    assert "context" in result
    
    # 구조화된 응답 검증
    message_content = result["message"]["content"]
    
    # JSON 파싱 가능한지 확인
    try:
        parsed_content = json.loads(message_content)
        assert "summary" in parsed_content
        assert "chart_data" in parsed_content
        assert isinstance(parsed_content["chart_data"], list)
    except json.JSONDecodeError:
        pytest.fail("Response content is not valid JSON")
    
    snapshot.assert_match(json.dumps(result, indent=4), "structured_result.json")


@pytest.mark.asyncio
async def test_ask_json_parsing_fallback(client, monkeypatch):
    """JSON 파싱 실패 시 텍스트 응답으로 fallback 테스트"""
    
    # GPT가 잘못된 JSON을 반환하도록 모킹
    def mock_invalid_json_response(*args, **kwargs):
        return ChatCompletion(
            object="chat.completion",
            choices=[Choice(
                message=ChatCompletionMessage(
                    role="assistant", 
                    content="Invalid JSON: {summary: 'test', chart_data:"  # 의도적으로 잘못된 JSON
                ), 
                finish_reason="stop", 
                index=0
            )],
            id="test-123",
            created=0,
            model="test-model",
            usage=CompletionUsage(completion_tokens=10, prompt_tokens=5, total_tokens=15)
        )
    
    # OpenAI 클라이언트 모킹
    with mock.patch.object(client.config["openai_client"].chat.completions, "create", mock_invalid_json_response):
        response = await client.post("/ask", json={
            "messages": [{"content": "테스트 질문", "role": "user"}],
            "context": {"overrides": {"structured_response": True}},
        })
    
    assert response.status_code == 200
    result = await response.get_json()
    
    # Fallback JSON 구조 확인
    message_content = result["message"]["content"]
    parsed_content = json.loads(message_content)
    
    assert "summary" in parsed_content
    assert "chart_data" in parsed_content
    assert isinstance(parsed_content["chart_data"], list)
    assert len(parsed_content["chart_data"]) == 0  # Fallback에서는 빈 배열
    
    # 원본 텍스트가 summary에 포함되었는지 확인
    assert "Invalid JSON" in parsed_content["summary"]


@pytest.mark.asyncio
async def test_ask_regular_response_unchanged(client, snapshot):
    """구조화된 응답이 비활성화된 경우 기존 응답 형식 유지 테스트"""
    response = await client.post(
        "/ask",
        json={
            "messages": [{"content": "What is the capital of France?", "role": "user"}],
            "context": {
                "overrides": {"structured_response": False},
            },
        },
    )
    
    assert response.status_code == 200
    result = await response.get_json()
    
    # 기존 응답 형식 확인 (단순 텍스트)
    message_content = result["message"]["content"]
    assert isinstance(message_content, str)
    
    # JSON이 아닌 일반 텍스트인지 확인
    try:
        json.loads(message_content)
        pytest.fail("Regular response should not be JSON")
    except json.JSONDecodeError:
        pass  # 예상된 동작
    
    snapshot.assert_match(json.dumps(result, indent=4), "regular_result.json")


@pytest.mark.asyncio
async def test_structured_response_with_chart_data(client, monkeypatch):
    """차트 데이터가 포함된 구조화된 응답 테스트"""
    
    def mock_structured_response(*args, **kwargs):
        structured_json = {
            "summary": "2023년 4분기 매출은 전년 동기 대비 12% 증가한 2.5억원을 기록했습니다 [sales_report.pdf]",
            "chart_data": [
                {"label": "Q1", "value": 200000000, "source": "sales_report.pdf"},
                {"label": "Q2", "value": 210000000, "source": "sales_report.pdf"},
                {"label": "Q3", "value": 230000000, "source": "sales_report.pdf"},
                {"label": "Q4", "value": 250000000, "source": "sales_report.pdf"}
            ]
        }
        
        return ChatCompletion(
            object="chat.completion",
            choices=[Choice(
                message=ChatCompletionMessage(
                    role="assistant", 
                    content=json.dumps(structured_json, ensure_ascii=False)
                ), 
                finish_reason="stop", 
                index=0
            )],
            id="test-123",
            created=0,
            model="test-model",
            usage=CompletionUsage(completion_tokens=100, prompt_tokens=50, total_tokens=150)
        )
    
    with mock.patch.object(client.config["openai_client"].chat.completions, "create", mock_structured_response):
        response = await client.post("/ask", json={
            "messages": [{"content": "분기별 매출 현황을 분석해줘", "role": "user"}],
            "context": {"overrides": {"structured_response": True}},
        })
    
    assert response.status_code == 200
    result = await response.get_json()
    
    message_content = result["message"]["content"]
    parsed_content = json.loads(message_content)
    
    # 요약 내용 확인
    assert "2023년 4분기 매출" in parsed_content["summary"]
    assert "[sales_report.pdf]" in parsed_content["summary"]
    
    # 차트 데이터 구조 확인
    chart_data = parsed_content["chart_data"]
    assert len(chart_data) == 4
    
    for data_point in chart_data:
        assert "label" in data_point
        assert "value" in data_point
        assert "source" in data_point
        assert isinstance(data_point["value"], int)


@pytest.mark.asyncio
async def test_structured_response_empty_chart_data(client, monkeypatch):
    """차트 데이터가 없는 경우의 구조화된 응답 테스트"""
    
    def mock_no_chart_response(*args, **kwargs):
        structured_json = {
            "summary": "현재 제공된 소스에서는 정확한 수치 데이터를 찾을 수 없습니다 [policy.pdf]",
            "chart_data": []
        }
        
        return ChatCompletion(
            object="chat.completion",
            choices=[Choice(
                message=ChatCompletionMessage(
                    role="assistant", 
                    content=json.dumps(structured_json, ensure_ascii=False)
                ), 
                finish_reason="stop", 
                index=0
            )],
            id="test-123",
            created=0,
            model="test-model",
            usage=CompletionUsage(completion_tokens=50, prompt_tokens=30, total_tokens=80)
        )
    
    with mock.patch.object(client.config["openai_client"].chat.completions, "create", mock_no_chart_response):
        response = await client.post("/ask", json={
            "messages": [{"content": "정책에 대해 알려줘", "role": "user"}],
            "context": {"overrides": {"structured_response": True}},
        })
    
    assert response.status_code == 200
    result = await response.get_json()
    
    message_content = result["message"]["content"]
    parsed_content = json.loads(message_content)
    
    assert "summary" in parsed_content
    assert "chart_data" in parsed_content
    assert isinstance(parsed_content["chart_data"], list)
    assert len(parsed_content["chart_data"]) == 0


@pytest.mark.asyncio  
async def test_structured_response_performance(client):
    """구조화된 응답의 성능이 기존 응답과 유사한지 테스트"""
    import time
    
    # 구조화된 응답 시간 측정
    start_time = time.time()
    response = await client.post("/ask", json={
        "messages": [{"content": "성능 테스트", "role": "user"}],
        "context": {"overrides": {"structured_response": True}},
    })
    structured_time = time.time() - start_time
    
    assert response.status_code == 200
    assert structured_time < 10.0  # 10초 이내 응답
    
    # 일반 응답 시간 측정
    start_time = time.time()
    response = await client.post("/ask", json={
        "messages": [{"content": "성능 테스트", "role": "user"}],
        "context": {"overrides": {"structured_response": False}},
    })
    regular_time = time.time() - start_time
    
    assert response.status_code == 200
    assert regular_time < 10.0  # 10초 이내 응답
    
    # 성능 차이가 크지 않은지 확인 (구조화된 응답이 2배 이상 느리지 않아야 함)
    assert structured_time < regular_time * 2.5


@pytest.mark.asyncio
async def test_structured_response_korean_content(client, monkeypatch):
    """한국어 콘텐츠가 포함된 구조화된 응답 테스트"""
    
    def mock_korean_response(*args, **kwargs):
        structured_json = {
            "summary": "젝사젠 회사의 2024년 주요 성과는 다음과 같습니다. AI 기술 개발에 집중하여 매출이 증가했습니다 [annual_report.pdf]",
            "chart_data": [
                {"label": "AI 솔루션", "value": 150000000, "source": "annual_report.pdf"},
                {"label": "컨설팅", "value": 80000000, "source": "annual_report.pdf"},
                {"label": "기타", "value": 20000000, "source": "annual_report.pdf"}
            ]
        }
        
        return ChatCompletion(
            object="chat.completion",
            choices=[Choice(
                message=ChatCompletionMessage(
                    role="assistant", 
                    content=json.dumps(structured_json, ensure_ascii=False)
                ), 
                finish_reason="stop", 
                index=0
            )],
            id="test-123",
            created=0,
            model="test-model",
            usage=CompletionUsage(completion_tokens=80, prompt_tokens=40, total_tokens=120)
        )
    
    with mock.patch.object(client.config["openai_client"].chat.completions, "create", mock_korean_response):
        response = await client.post("/ask", json={
            "messages": [{"content": "젝사젠 회사 실적을 분석해줘", "role": "user"}],
            "context": {"overrides": {"structured_response": True}},
        })
    
    assert response.status_code == 200
    result = await response.get_json()
    
    message_content = result["message"]["content"]
    parsed_content = json.loads(message_content)
    
    # 한국어 콘텐츠 확인
    assert "젝사젠" in parsed_content["summary"]
    assert "AI 기술" in parsed_content["summary"]
    
    # 차트 데이터의 한국어 라벨 확인
    chart_data = parsed_content["chart_data"]
    labels = [item["label"] for item in chart_data]
    assert "AI 솔루션" in labels
    assert "컨설팅" in labels