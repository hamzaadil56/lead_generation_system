from typing import Generic, TypeVar

from pydantic import BaseModel, Field, computed_field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Envelope for every list endpoint.

    `pages` is at least 1 so a UI never renders "page 1 of 0" on an empty
    result set.

    `pages` and `has_next` are `@computed_field` rather than plain
    `@property`: Pydantic v2 does not serialise plain properties, so a
    property here would be visible in Python but silently absent from the
    JSON body the frontend's pagination control reads.
    """
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))   # ceil division

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_next(self) -> bool:
        return self.page < self.pages
