import dataclasses
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from dbgpt._private.pydantic import BaseModel
from dbgpt.core._private.example_base import ExampleSelector
from dbgpt.core.awel import MapOperator
from dbgpt.core.interface.output_parser import BaseOutputParser
from dbgpt.core.interface.storage import (
    InMemoryStorage,
    QuerySpec,
    ResourceIdentifier,
    StorageInterface,
    StorageItem,
)
from dbgpt.util.formatting import formatter, no_strict_formatter


def _jinja2_formatter(template: str, **kwargs: Any) -> str:
    """Format a template using jinja2."""
    try:
        from jinja2 import Template
    except ImportError:
        raise ImportError(
            "jinja2 not installed, which is needed to use the jinja2_formatter. "
            "Please install it with `pip install jinja2`."
        )

    return Template(template).render(**kwargs)


_DEFAULT_FORMATTER_MAPPING: Dict[str, Callable] = {
    "f-string": lambda is_strict: formatter.format
    if is_strict
    else no_strict_formatter.format,
    "jinja2": lambda is_strict: _jinja2_formatter,
}


class PromptTemplate(BaseModel, ABC):
    input_variables: List[str]
    """A list of the names of the variables the prompt template expects."""
    template_scene: Optional[str]
    template_define: Optional[str]
    """this template define"""
    template: Optional[str]
    """The prompt template."""
    template_format: str = "f-string"
    """strict template will check template args"""
    template_is_strict: bool = True
    """The format of the prompt template. Options are: 'f-string', 'jinja2'."""
    response_format: Optional[str]
    """default use stream out"""
    stream_out: bool = True
    """"""
    output_parser: BaseOutputParser = None
    """"""
    sep: str = "###"

    example_selector: ExampleSelector = None

    need_historical_messages: bool = False

    temperature: float = 0.6
    max_new_tokens: int = 1024

    class Config:
        """Configuration for this pydantic object."""

        arbitrary_types_allowed = True

    @property
    def _prompt_type(self) -> str:
        """Return the prompt type key."""
        return "prompt"

    def format(self, **kwargs: Any) -> str:
        """Format the prompt with the inputs."""
        if self.template:
            if self.response_format:
                kwargs["response"] = json.dumps(
                    self.response_format, ensure_ascii=False, indent=4
                )
            return _DEFAULT_FORMATTER_MAPPING[self.template_format](
                self.template_is_strict
            )(self.template, **kwargs)

    @staticmethod
    def from_template(template: str) -> "PromptTemplateOperator":
        """Create a prompt template from a template string."""
        return PromptTemplateOperator(
            PromptTemplate(template=template, input_variables=[])
        )


@dataclasses.dataclass
class PromptTemplateIdentifier(ResourceIdentifier):
    identifier_split: str = dataclasses.field(default="___$$$$___", init=False)
    prompt_name: str
    prompt_language: Optional[str] = None
    sys_code: Optional[str] = None
    model: Optional[str] = None

    def __post_init__(self):
        if self.prompt_name is None:
            raise ValueError("prompt_name cannot be None")

        if any(
            self.identifier_split in key
            for key in [
                self.prompt_name,
                self.prompt_language,
                self.sys_code,
                self.model,
            ]
            if key is not None
        ):
            raise ValueError(
                f"identifier_split {self.identifier_split} is not allowed in prompt_name, prompt_language, sys_code, model"
            )

    @property
    def str_identifier(self) -> str:
        return self.identifier_split.join(
            key
            for key in [
                self.prompt_name,
                self.prompt_language,
                self.sys_code,
                self.model,
            ]
            if key is not None
        )

    def to_dict(self) -> Dict:
        return {
            "prompt_name": self.prompt_name,
            "prompt_language": self.prompt_language,
            "sys_code": self.sys_code,
            "model": self.model,
        }


@dataclasses.dataclass
class StoragePromptTemplate(StorageItem):
    prompt_name: str
    content: Optional[str] = None
    prompt_language: Optional[str] = None
    prompt_format: Optional[str] = None
    input_variables: Optional[str] = None
    model: Optional[str] = None
    chat_scene: Optional[str] = None
    sub_chat_scene: Optional[str] = None
    prompt_type: Optional[str] = None
    user_name: Optional[str] = None
    sys_code: Optional[str] = None
    _identifier: PromptTemplateIdentifier = dataclasses.field(init=False)

    def __post_init__(self):
        self._identifier = PromptTemplateIdentifier(
            prompt_name=self.prompt_name,
            prompt_language=self.prompt_language,
            sys_code=self.sys_code,
            model=self.model,
        )
        self._check()  # Assuming _check() is a method you need to call after initialization

    def to_prompt_template(self) -> PromptTemplate:
        """Convert the storage prompt template to a prompt template."""
        input_variables = (
            None
            if not self.input_variables
            else self.input_variables.strip().split(",")
        )
        return PromptTemplate(
            input_variables=input_variables,
            template=self.content,
            template_scene=self.chat_scene,
            prompt_name=self.prompt_name,
            template_format=self.prompt_format,
        )

    @staticmethod
    def from_prompt_template(
        prompt_template: PromptTemplate,
        prompt_name: str,
        prompt_language: Optional[str] = None,
        prompt_type: Optional[str] = None,
        sys_code: Optional[str] = None,
        user_name: Optional[str] = None,
        sub_chat_scene: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> "StoragePromptTemplate":
        """Convert a prompt template to a storage prompt template.

        Args:
            prompt_template (PromptTemplate): The prompt template to convert from.
            prompt_name (str): The name of the prompt.
            prompt_language (Optional[str], optional): The language of the prompt. Defaults to None. e.g. zh-cn, en.
            prompt_type (Optional[str], optional): The type of the prompt. Defaults to None. e.g. common, private.
            sys_code (Optional[str], optional): The system code of the prompt. Defaults to None.
            user_name (Optional[str], optional): The username of the prompt. Defaults to None.
            sub_chat_scene (Optional[str], optional): The sub chat scene of the prompt. Defaults to None.
            model (Optional[str], optional): The model name of the prompt. Defaults to None.
            kwargs (Dict): Other params to build the storage prompt template.
        """
        input_variables = prompt_template.input_variables or kwargs.get(
            "input_variables"
        )
        if input_variables and isinstance(input_variables, list):
            input_variables = ",".join(input_variables)
        return StoragePromptTemplate(
            prompt_name=prompt_name,
            sys_code=sys_code,
            user_name=user_name,
            input_variables=input_variables,
            model=model,
            content=prompt_template.template or kwargs.get("content"),
            prompt_language=prompt_language,
            prompt_format=prompt_template.template_format
            or kwargs.get("prompt_format"),
            chat_scene=prompt_template.template_scene or kwargs.get("chat_scene"),
            sub_chat_scene=sub_chat_scene,
            prompt_type=prompt_type,
        )

    @property
    def identifier(self) -> PromptTemplateIdentifier:
        return self._identifier

    def merge(self, other: "StorageItem") -> None:
        """Merge the other item into the current item.

        Args:
            other (StorageItem): The other item to merge
        """
        if not isinstance(other, StoragePromptTemplate):
            raise ValueError(
                f"Cannot merge {type(other)} into {type(self)} because they are not the same type."
            )
        self.from_object(other)

    def to_dict(self) -> Dict:
        return {
            "prompt_name": self.prompt_name,
            "content": self.content,
            "prompt_language": self.prompt_language,
            "prompt_format": self.prompt_format,
            "input_variables": self.input_variables,
            "model": self.model,
            "chat_scene": self.chat_scene,
            "sub_chat_scene": self.sub_chat_scene,
            "prompt_type": self.prompt_type,
            "user_name": self.user_name,
            "sys_code": self.sys_code,
        }

    def _check(self):
        if self.prompt_name is None:
            raise ValueError("prompt_name cannot be None")
        if self.content is None:
            raise ValueError("content cannot be None")

    def from_object(self, template: "StoragePromptTemplate") -> None:
        """Load the prompt template from an existing prompt template object.

        Args:
            template (PromptTemplate): The prompt template to load from.
        """
        self.content = template.content
        self.prompt_format = template.prompt_format
        self.input_variables = template.input_variables
        self.model = template.model
        self.chat_scene = template.chat_scene
        self.sub_chat_scene = template.sub_chat_scene
        self.prompt_type = template.prompt_type
        self.user_name = template.user_name


class PromptManager:
    """The manager class for prompt templates.

    Simple wrapper for the storage interface.

    Examples:

        .. code-block:: python

            # Default use InMemoryStorage
            prompt_manager = PromptManager()
            prompt_template = PromptTemplate(
                template="hello {input}",
                input_variables=["input"],
                template_scene="chat_normal",
            )
            prompt_manager.save(prompt_template, prompt_name="hello")
            prompt_template_list = prompt_manager.list()
            prompt_template_list = prompt_manager.prefer_query("hello")

        With a custom storage interface.

        .. code-block:: python

            from dbgpt.core.interface.storage import InMemoryStorage

            prompt_manager = PromptManager(InMemoryStorage())
            prompt_template = PromptTemplate(
                template="hello {input}",
                input_variables=["input"],
                template_scene="chat_normal",
            )
            prompt_manager.save(prompt_template, prompt_name="hello")
            prompt_template_list = prompt_manager.list()
            prompt_template_list = prompt_manager.prefer_query("hello")


    """

    def __init__(
        self, storage: Optional[StorageInterface[StoragePromptTemplate, Any]] = None
    ):
        if storage is None:
            storage = InMemoryStorage()
        self._storage = storage

    @property
    def storage(self) -> StorageInterface[StoragePromptTemplate, Any]:
        """The storage interface for prompt templates."""
        return self._storage

    def prefer_query(
        self,
        prompt_name: str,
        sys_code: Optional[str] = None,
        prefer_prompt_language: Optional[str] = None,
        prefer_model: Optional[str] = None,
        **kwargs,
    ) -> List[StoragePromptTemplate]:
        """Query prompt templates from storage with prefer params.

        Sometimes, we want to query prompt templates with prefer params(e.g. some language or some model).
        This method will query prompt templates with prefer params first, if not found, will query all prompt templates.

        Examples:

            Query a prompt template.
            .. code-block:: python

                prompt_template_list = prompt_manager.prefer_query("hello")

            Query with sys_code and username.

            .. code-block:: python

                prompt_template_list = prompt_manager.prefer_query(
                    "hello", sys_code="sys_code", user_name="user_name"
                )

            Query with prefer prompt language.

            .. code-block:: python

                # First query with prompt name "hello" exactly.
                # Second filter with prompt language "zh-cn", if not found, will return all prompt templates.
                prompt_template_list = prompt_manager.prefer_query(
                    "hello", prefer_prompt_language="zh-cn"
                )

            Query with prefer model.

            .. code-block:: python

                # First query with prompt name "hello" exactly.
                # Second filter with model "vicuna-13b-v1.5", if not found, will return all prompt templates.
                prompt_template_list = prompt_manager.prefer_query(
                    "hello", prefer_model="vicuna-13b-v1.5"
                )

        Args:
            prompt_name (str): The name of the prompt template.
            sys_code (Optional[str], optional): The system code of the prompt template. Defaults to None.
            prefer_prompt_language (Optional[str], optional): The language of the prompt template. Defaults to None.
            prefer_model (Optional[str], optional): The model of the prompt template. Defaults to None.
            kwargs (Dict): Other query params(If some key and value not None, wo we query it exactly).
        """
        query_spec = QuerySpec(
            conditions={
                "prompt_name": prompt_name,
                "sys_code": sys_code,
                **kwargs,
            }
        )
        queries: List[StoragePromptTemplate] = self.storage.query(
            query_spec, StoragePromptTemplate
        )
        if not queries:
            return []
        if prefer_prompt_language:
            prefer_prompt_language = prefer_prompt_language.lower()
            temp_queries = [
                query
                for query in queries
                if query.prompt_language
                and query.prompt_language.lower() == prefer_prompt_language
            ]
            if temp_queries:
                queries = temp_queries
        if prefer_model:
            prefer_model = prefer_model.lower()
            temp_queries = [
                query
                for query in queries
                if query.model and query.model.lower() == prefer_model
            ]
            if temp_queries:
                queries = temp_queries
        return queries

    def save(self, prompt_template: PromptTemplate, prompt_name: str, **kwargs) -> None:
        """Save a prompt template to storage.

        Examples:

            .. code-block:: python

                prompt_template = PromptTemplate(
                    template="hello {input}",
                    input_variables=["input"],
                    template_scene="chat_normal",
                    prompt_name="hello",
                )
                prompt_manager.save(prompt_template)

            Save with sys_code and username.

            .. code-block:: python

                prompt_template = PromptTemplate(
                    template="hello {input}",
                    input_variables=["input"],
                    template_scene="chat_normal",
                    prompt_name="hello",
                )
                prompt_manager.save(
                    prompt_template, sys_code="sys_code", user_name="user_name"
                )

        Args:
            prompt_template (PromptTemplate): The prompt template to save.
            prompt_name (str): The name of the prompt template.
            kwargs (Dict): Other params to build the storage prompt template.
                More details in :meth:`~StoragePromptTemplate.from_prompt_template`.
        """
        storage_prompt_template = StoragePromptTemplate.from_prompt_template(
            prompt_template, prompt_name, **kwargs
        )
        self.storage.save(storage_prompt_template)

    def list(self, **kwargs) -> List[StoragePromptTemplate]:
        """List prompt templates from storage.

        Examples:

            List all prompt templates.
            .. code-block:: python

                all_prompt_templates = prompt_manager.list()

            List with sys_code and username.

            .. code-block:: python

                templates = prompt_manager.list(
                    sys_code="sys_code", user_name="user_name"
                )

        Args:
            kwargs (Dict): Other query params.
        """
        query_spec = QuerySpec(conditions=kwargs)
        return self.storage.query(query_spec, StoragePromptTemplate)

    def delete(
        self,
        prompt_name: str,
        prompt_language: Optional[str] = None,
        sys_code: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """Delete a prompt template from storage.

        Examples:

            Delete a prompt template.

            .. code-block:: python

                prompt_manager.delete("hello")

            Delete with sys_code and username.

            .. code-block:: python

                prompt_manager.delete(
                    "hello", sys_code="sys_code", user_name="user_name"
                )

        Args:
            prompt_name (str): The name of the prompt template.
            prompt_language (Optional[str], optional): The language of the prompt template. Defaults to None.
            sys_code (Optional[str], optional): The system code of the prompt template. Defaults to None.
            model (Optional[str], optional): The model of the prompt template. Defaults to None.
        """
        identifier = PromptTemplateIdentifier(
            prompt_name=prompt_name,
            prompt_language=prompt_language,
            sys_code=sys_code,
            model=model,
        )
        self.storage.delete(identifier)


class PromptTemplateOperator(MapOperator[Dict, str]):
    def __init__(self, prompt_template: PromptTemplate, **kwargs: Any):
        super().__init__(**kwargs)
        self._prompt_template = prompt_template

    async def map(self, input_value: Dict) -> str:
        return self._prompt_template.format(**input_value)
