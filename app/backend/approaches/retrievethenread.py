import json
import logging
from typing import Any, Optional, cast

from azure.search.documents.agent.aio import KnowledgeAgentRetrievalClient
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorQuery
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from approaches.approach import Approach, DataPoints, ExtraInfo, ThoughtStep
from approaches.promptmanager import PromptManager
from core.authentication import AuthenticationHelper

logger = logging.getLogger(__name__)


class RetrieveThenReadApproach(Approach):
    """
    Simple retrieve-then-read implementation, using the AI Search and OpenAI APIs directly. It first retrieves
    top documents from search, then constructs a prompt with them, and then uses OpenAI to generate an completion
    (answer) with that prompt.
    """

    def __init__(
        self,
        *,
        search_client: SearchClient,
        search_index_name: str,
        agent_model: Optional[str],
        agent_deployment: Optional[str],
        agent_client: KnowledgeAgentRetrievalClient,
        auth_helper: AuthenticationHelper,
        openai_client: AsyncOpenAI,
        chatgpt_model: str,
        chatgpt_deployment: Optional[str],  # Not needed for non-Azure OpenAI
        embedding_model: str,
        embedding_deployment: Optional[str],  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embedding_dimensions: int,
        embedding_field: str,
        sourcepage_field: str,
        content_field: str,
        query_language: str,
        query_speller: str,
        prompt_manager: PromptManager,
        reasoning_effort: Optional[str] = None,
    ):
        self.search_client = search_client
        self.search_index_name = search_index_name
        self.agent_model = agent_model
        self.agent_deployment = agent_deployment
        self.agent_client = agent_client
        self.chatgpt_deployment = chatgpt_deployment
        self.openai_client = openai_client
        self.auth_helper = auth_helper
        self.chatgpt_model = chatgpt_model
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.chatgpt_deployment = chatgpt_deployment
        self.embedding_deployment = embedding_deployment
        self.embedding_field = embedding_field
        self.sourcepage_field = sourcepage_field
        self.content_field = content_field
        self.query_language = query_language
        self.query_speller = query_speller
        self.prompt_manager = prompt_manager
        self.answer_prompt = self.prompt_manager.load_prompt("ask_answer_question.prompty")
        self.structured_answer_prompt = self.prompt_manager.load_prompt("ask_answer_question_structured.prompty")
        self.reasoning_effort = reasoning_effort
        self.include_token_usage = True

    async def run(
        self,
        messages: list[ChatCompletionMessageParam],
        session_state: Any = None,
        context: dict[str, Any] = {},
    ) -> dict[str, Any]:
        overrides = context.get("overrides", {})
        auth_claims = context.get("auth_claims", {})
        use_agentic_retrieval = True if overrides.get("use_agentic_retrieval") else False
        use_structured_response = overrides.get("structured_response", False)
        q = messages[-1]["content"]
        if not isinstance(q, str):
            raise ValueError("The most recent message content must be a string.")

        if use_agentic_retrieval:
            extra_info = await self.run_agentic_retrieval_approach(messages, overrides, auth_claims)
        else:
            extra_info = await self.run_search_approach(messages, overrides, auth_claims)

        # Choose appropriate prompt based on structured response requirement
        selected_prompt = self.structured_answer_prompt if use_structured_response else self.answer_prompt

        # Process results
        messages = self.prompt_manager.render_prompt(
            selected_prompt,
            self.get_system_prompt_variables(overrides.get("prompt_template"))
            | {"user_query": q, "text_sources": extra_info.data_points.text},
        )

        chat_completion = cast(
            ChatCompletion,
            await self.create_chat_completion(
                self.chatgpt_deployment,
                self.chatgpt_model,
                messages=messages,
                overrides=overrides,
                # Increase token limit for structured responses to reduce JSON truncation
                response_token_limit=self.get_response_token_limit(
                    self.chatgpt_model,
                    2048 if use_structured_response else 1024,
                ),
            ),
        )
        extra_info.thoughts.append(
            self.format_thought_step_for_chatcompletion(
                title="Prompt to generate answer",
                messages=messages,
                overrides=overrides,
                model=self.chatgpt_model,
                deployment=self.chatgpt_deployment,
                usage=chat_completion.usage,
            )
        )

        # Handle structured response with JSON parsing and fallback
        response_content = chat_completion.choices[0].message.content
        if use_structured_response:
            response_content = self._handle_structured_response(response_content)

        return {
            "message": {
                "content": response_content,
                "role": chat_completion.choices[0].message.role,
            },
            "context": extra_info,
            "session_state": session_state,
        }

    async def run_search_approach(
        self, messages: list[ChatCompletionMessageParam], overrides: dict[str, Any], auth_claims: dict[str, Any]
    ):
        use_text_search = overrides.get("retrieval_mode") in ["text", "hybrid", None]
        use_vector_search = overrides.get("retrieval_mode") in ["vectors", "hybrid", None]
        use_semantic_ranker = True if overrides.get("semantic_ranker") else False
        use_query_rewriting = True if overrides.get("query_rewriting") else False
        use_semantic_captions = True if overrides.get("semantic_captions") else False
        top = overrides.get("top", 3)
        minimum_search_score = overrides.get("minimum_search_score", 0.0)
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0.0)
        filter = self.build_filter(overrides, auth_claims)
        q = str(messages[-1]["content"])

        # If retrieval mode includes vectors, compute an embedding for the query
        vectors: list[VectorQuery] = []
        if use_vector_search:
            vectors.append(await self.compute_text_embedding(q))

        results = await self.search(
            top,
            q,
            filter,
            vectors,
            use_text_search,
            use_vector_search,
            use_semantic_ranker,
            use_semantic_captions,
            minimum_search_score,
            minimum_reranker_score,
            use_query_rewriting,
        )

        text_sources = self.get_sources_content(results, use_semantic_captions, use_image_citation=False)

        return ExtraInfo(
            DataPoints(text=text_sources),
            thoughts=[
                ThoughtStep(
                    "Search using user query",
                    q,
                    {
                        "use_semantic_captions": use_semantic_captions,
                        "use_semantic_ranker": use_semantic_ranker,
                        "use_query_rewriting": use_query_rewriting,
                        "top": top,
                        "filter": filter,
                        "use_vector_search": use_vector_search,
                        "use_text_search": use_text_search,
                    },
                ),
                ThoughtStep(
                    "Search results",
                    [result.serialize_for_results() for result in results],
                ),
            ],
        )

    async def run_agentic_retrieval_approach(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
    ):
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0)
        search_index_filter = self.build_filter(overrides, auth_claims)
        top = overrides.get("top", 3)
        max_subqueries = overrides.get("max_subqueries", 10)
        results_merge_strategy = overrides.get("results_merge_strategy", "interleaved")
        # 50 is the amount of documents that the reranker can process per query
        max_docs_for_reranker = max_subqueries * 50

        response, results = await self.run_agentic_retrieval(
            messages,
            self.agent_client,
            search_index_name=self.search_index_name,
            top=top,
            filter_add_on=search_index_filter,
            minimum_reranker_score=minimum_reranker_score,
            max_docs_for_reranker=max_docs_for_reranker,
            results_merge_strategy=results_merge_strategy,
        )

        text_sources = self.get_sources_content(results, use_semantic_captions=False, use_image_citation=False)

        extra_info = ExtraInfo(
            DataPoints(text=text_sources),
            thoughts=[
                ThoughtStep(
                    "Use agentic retrieval",
                    messages,
                    {
                        "reranker_threshold": minimum_reranker_score,
                        "max_docs_for_reranker": max_docs_for_reranker,
                        "results_merge_strategy": results_merge_strategy,
                        "filter": search_index_filter,
                    },
                ),
                ThoughtStep(
                    f"Agentic retrieval results (top {top})",
                    [result.serialize_for_results() for result in results],
                    {
                        "query_plan": (
                            [activity.as_dict() for activity in response.activity] if response.activity else None
                        ),
                        "model": self.agent_model,
                        "deployment": self.agent_deployment,
                    },
                ),
            ],
        )
        return extra_info

    def _handle_structured_response(self, response_content: str) -> str:
        """
        Handle structured JSON response with fallback to plain text.
        
        Args:
            response_content: The raw response content from GPT
            
        Returns:
            Either valid JSON string or fallback plain text
        """
        if not response_content:
            return json.dumps({
                "summary": "No response generated.",
                "chart_data": []
            })

        try:
            # Try to parse as JSON to validate structure
            parsed_json = json.loads(response_content)
            
            # Validate required fields
            if not isinstance(parsed_json, dict):
                raise ValueError("Response is not a JSON object")
            
            if "summary" not in parsed_json or "chart_data" not in parsed_json:
                raise ValueError("Missing required fields: summary or chart_data")
            
            # Validate chart_data is an array
            if not isinstance(parsed_json["chart_data"], list):
                raise ValueError("chart_data must be an array")
            
            # Return the valid JSON string
            return response_content
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse structured response as JSON: {e}")
            logger.warning(f"Raw response: {response_content}")
            # Attempt to salvage JSON by extracting the largest valid JSON object fragment
            try:
                start_idx = response_content.find("{")
                end_idx = response_content.rfind("}")
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    candidate = response_content[start_idx : end_idx + 1]
                    candidate_json = json.loads(candidate)

                    # Ensure required fields exist; if missing, wrap into expected structure
                    if not isinstance(candidate_json, dict):
                        raise ValueError("Candidate JSON is not an object")

                    if "summary" not in candidate_json or "chart_data" not in candidate_json:
                        candidate_json = {
                            "summary": candidate_json if isinstance(candidate_json, str) else response_content,
                            "chart_data": [],
                        }

                    if not isinstance(candidate_json.get("chart_data", []), list):
                        candidate_json["chart_data"] = []

                    return json.dumps(candidate_json, ensure_ascii=False)
            except Exception as salvage_error:
                logger.warning(f"Structured response salvage attempt failed: {salvage_error}")

            # Fallback: wrap the plain text response in JSON structure
            fallback_response = {
                "summary": response_content,
                "chart_data": []
            }
            
            return json.dumps(fallback_response, ensure_ascii=False)
