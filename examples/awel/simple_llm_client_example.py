"""AWEL: Simple llm client example

    DB-GPT will automatically load and execute the current file after startup.

    Examples:

        Call with non-streaming response.
        .. code-block:: shell

            DBGPT_SERVER="http://127.0.0.1:5000"
            curl -X POST $DBGPT_SERVER/api/v1/awel/trigger/examples/simple_client/chat/completions \
            -H "Content-Type: application/json" -d '{
                "model": "proxyllm",
                "messages": "hello"
            }'

        Call with streaming response.
        .. code-block:: shell

            curl -X POST $DBGPT_SERVER/api/v1/awel/trigger/examples/simple_client/chat/completions \
            -H "Content-Type: application/json" -d '{
                "model": "proxyllm",
                "messages": "hello",
                "stream": true
            }'

        Call model and count token.
         .. code-block:: shell

            curl -X POST $DBGPT_SERVER/api/v1/awel/trigger/examples/simple_client/count_token \
            -H "Content-Type: application/json" -d '{
                "model": "proxyllm",
                "messages": "hello"
            }'

"""
from typing import Dict, Any, Optional, Union, List
import logging
from dbgpt._private.pydantic import BaseModel, Field
from dbgpt.core.awel import (
    DAG,
    HttpTrigger,
    MapOperator,
    JoinOperator,
)
from dbgpt.core import LLMClient

from dbgpt.core.operator import (
    LLMBranchOperator,
    LLMOperator,
    StreamingLLMOperator,
    RequestBuildOperator,
)
from dbgpt.model import OpenAIStreamingOperator, MixinLLMOperator

logger = logging.getLogger(__name__)


class TriggerReqBody(BaseModel):
    messages: Union[str, List[Dict[str, str]]] = Field(
        ..., description="User input messages"
    )
    model: str = Field(..., description="Model name")
    stream: Optional[bool] = Field(default=False, description="Whether return stream")


class MyLLMOperator(MixinLLMOperator, LLMOperator):
    def __init__(self, llm_client: Optional[LLMClient] = None, **kwargs):
        super().__init__(llm_client)
        LLMOperator.__init__(self, llm_client, **kwargs)


class MyStreamingLLMOperator(MixinLLMOperator, StreamingLLMOperator):
    def __init__(self, llm_client: Optional[LLMClient] = None, **kwargs):
        super().__init__(llm_client)
        StreamingLLMOperator.__init__(self, llm_client, **kwargs)


class MyModelToolOperator(
    MixinLLMOperator, MapOperator[TriggerReqBody, Dict[str, Any]]
):
    def __init__(self, llm_client: Optional[LLMClient] = None, **kwargs):
        super().__init__(llm_client)
        MapOperator.__init__(self, llm_client, **kwargs)

    async def map(self, input_value: TriggerReqBody) -> Dict[str, Any]:
        prompt_tokens = await self.llm_client.count_token(
            input_value.model, input_value.messages
        )
        available_models = await self.llm_client.models()
        return {
            "prompt_tokens": prompt_tokens,
            "available_models": available_models,
        }


with DAG("dbgpt_awel_simple_llm_client_generate") as client_generate_dag:
    # Receive http request and trigger dag to run.
    trigger = HttpTrigger(
        "/examples/simple_client/chat/completions",
        methods="POST",
        request_body=TriggerReqBody,
        streaming_predict_func=lambda req: req.stream,
    )
    request_handle_task = RequestBuildOperator()
    llm_task = MyLLMOperator(task_name="llm_task")
    streaming_llm_task = MyStreamingLLMOperator(task_name="streaming_llm_task")
    branch_task = LLMBranchOperator(
        stream_task_name="streaming_llm_task", no_stream_task_name="llm_task"
    )
    model_parse_task = MapOperator(lambda out: out.to_dict())
    openai_format_stream_task = OpenAIStreamingOperator()
    result_join_task = JoinOperator(
        combine_function=lambda not_stream_out, stream_out: not_stream_out or stream_out
    )

    trigger >> request_handle_task >> branch_task
    branch_task >> llm_task >> model_parse_task >> result_join_task
    branch_task >> streaming_llm_task >> openai_format_stream_task >> result_join_task


with DAG("dbgpt_awel_simple_llm_client_count_token") as client_count_token_dag:
    # Receive http request and trigger dag to run.
    trigger = HttpTrigger(
        "/examples/simple_client/count_token",
        methods="POST",
        request_body=TriggerReqBody,
    )
    model_task = MyModelToolOperator()
    trigger >> model_task


if __name__ == "__main__":
    if client_generate_dag.leaf_nodes[0].dev_mode:
        # Development mode, you can run the dag locally for debugging.
        from dbgpt.core.awel import setup_dev_environment

        dags = [client_generate_dag, client_count_token_dag]
        setup_dev_environment(dags, port=5555)
    else:
        # Production mode, DB-GPT will automatically load and execute the current file after startup.
        pass
