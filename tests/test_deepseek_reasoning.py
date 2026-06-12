import os
import unittest

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompt_values import ChatPromptValue
from pydantic import BaseModel

from marketmind_ai.llm_clients.openai_client import (
    DeepSeekChatOpenAI,
    NormalizedChatOpenAI,
    _input_to_messages,
)


class SampleModel(BaseModel):
    answer: str


class TestInputToMessages(unittest.TestCase):
    def test_list_input_returned_as_is(self):
        msgs = [HumanMessage(content="hi")]
        self.assertIs(_input_to_messages(msgs), msgs)

    def test_chat_prompt_value_unwrapped(self):
        msgs = [HumanMessage(content="hi")]
        prompt_value = ChatPromptValue(messages=msgs)
        self.assertEqual(_input_to_messages(prompt_value), msgs)

    def test_string_input_yields_empty_list(self):
        self.assertEqual(_input_to_messages("hello"), [])


class TestDeepSeekReasoningContent(unittest.TestCase):
    def _client(self):
        os.environ.setdefault("DEEPSEEK_API_KEY", "placeholder")
        return DeepSeekChatOpenAI(
            model="deepseek-v4-flash",
            api_key="placeholder",
            base_url="https://api.deepseek.com",
        )

    def test_capture_on_receive(self):
        client = self._client()
        result = client._create_chat_result(
            {
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Plan: buy NVDA.",
                            "reasoning_content": "Step 1: trend is up. Step 2: ...",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )
        ai = result.generations[0].message
        self.assertEqual(ai.additional_kwargs["reasoning_content"], "Step 1: trend is up. Step 2: ...")

    def test_propagate_on_send(self):
        client = self._client()
        prior = AIMessage(
            content="Plan",
            additional_kwargs={"reasoning_content": "weighed bull case"},
        )
        new_user = HumanMessage(content="Refine.")
        payload = client._get_request_payload([prior, new_user])
        assistant_dicts = [message for message in payload["messages"] if message.get("role") == "assistant"]
        self.assertTrue(assistant_dicts)
        self.assertEqual(assistant_dicts[0]["reasoning_content"], "weighed bull case")

    def test_propagate_through_chat_prompt_value(self):
        client = self._client()
        prior = AIMessage(
            content="Plan",
            additional_kwargs={"reasoning_content": "weighed bull case"},
        )
        prompt_value = ChatPromptValue(messages=[prior, HumanMessage(content="Refine.")])
        payload = client._get_request_payload(prompt_value)
        assistant_dicts = [message for message in payload["messages"] if message.get("role") == "assistant"]
        self.assertEqual(assistant_dicts[0]["reasoning_content"], "weighed bull case")


class TestDeepSeekReasonerStructuredOutput(unittest.TestCase):
    def test_with_structured_output_raises_for_reasoner(self):
        client = DeepSeekChatOpenAI(
            model="deepseek-reasoner",
            api_key="placeholder",
            base_url="https://api.deepseek.com",
        )
        with self.assertRaises(NotImplementedError):
            client.with_structured_output(SampleModel)

    def test_with_structured_output_works_for_v4(self):
        client = DeepSeekChatOpenAI(
            model="deepseek-v4-flash",
            api_key="placeholder",
            base_url="https://api.deepseek.com",
        )
        wrapped = client.with_structured_output(SampleModel)
        self.assertIsNotNone(wrapped)


class TestBaseClassIsolation(unittest.TestCase):
    def test_normalized_does_not_propagate_reasoning_content(self):
        self.assertTrue(
            not hasattr(NormalizedChatOpenAI, "_get_request_payload")
            or (
                NormalizedChatOpenAI._get_request_payload
                is NormalizedChatOpenAI.__bases__[0]._get_request_payload
            )
        )


if __name__ == "__main__":
    unittest.main()
