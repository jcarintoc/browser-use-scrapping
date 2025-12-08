"""
Pydantic models for HAR analysis and API endpoint discovery.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from enum import Enum


class HTTPMethod(str, Enum):
    """HTTP methods"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class AuthMethod(str, Enum):
    """Authentication methods detected"""
    NONE = "none"
    COOKIE = "cookie"
    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"
    OAUTH = "oauth"


class APIParameter(BaseModel):
    """API parameter (query, body, or header)"""
    name: str = Field(description="Parameter name")
    location: str = Field(description="Where parameter appears: query, body, header")
    example_value: Optional[str] = Field(default=None, description="Example value from HAR")
    required: bool = Field(default=True, description="Whether parameter is required")
    param_type: Optional[str] = Field(default=None, description="Data type (string, int, bool, etc)")


class APIEndpoint(BaseModel):
    """Single discovered API endpoint"""

    # Identification
    method: HTTPMethod = Field(description="HTTP method")
    path: str = Field(description="URL path (without domain)")
    full_url: str = Field(description="Full URL example from HAR")
    domain: str = Field(description="API domain/hostname")

    # Classification
    endpoint_name: str = Field(description="Descriptive name for this endpoint")
    purpose: str = Field(description="What this endpoint does (inferred by LLM)")
    category: str = Field(description="Category: data_fetch, user_action, authentication, etc.")

    # Request Details
    parameters: List[APIParameter] = Field(default_factory=list, description="All parameters")
    required_headers: Dict[str, str] = Field(default_factory=dict, description="Important headers")
    auth_method: AuthMethod = Field(default=AuthMethod.NONE, description="Authentication method used")

    # Response Details
    response_format: str = Field(description="Response content type (json, html, xml, etc)")
    response_structure: Optional[str] = Field(default=None, description="Brief description of response structure")
    example_response: Optional[str] = Field(default=None, description="Truncated example response (first 500 chars)")

    # Metadata
    status_code: int = Field(description="HTTP status code from example")
    call_frequency: int = Field(default=1, description="How many times this endpoint was called in HAR")
    timing_avg_ms: Optional[float] = Field(default=None, description="Average response time in ms")


class HARAnalysisResult(BaseModel):
    """Complete analysis result"""

    # Metadata
    website_name: str = Field(description="Website identifier from config")
    analysis_timestamp: str = Field(description="When analysis was performed")
    original_task: str = Field(description="Original scraping task from config")

    # HAR Statistics
    total_requests: int = Field(description="Total requests in original HAR")
    filtered_requests: int = Field(description="Requests after filtering")
    filter_stats: Dict[str, int] = Field(description="Breakdown of what was filtered")

    # API Discovery
    endpoints: List[APIEndpoint] = Field(description="All discovered API endpoints")
    total_endpoints: int = Field(description="Number of unique endpoints")

    # Authentication Summary
    auth_methods_detected: List[AuthMethod] = Field(description="All auth methods found")
    cookie_names: List[str] = Field(default_factory=list, description="Important cookie names")
    auth_headers: List[str] = Field(default_factory=list, description="Important auth headers")

    # Additional Context
    domains_accessed: List[str] = Field(description="All unique domains accessed")
    notes: Optional[str] = Field(default=None, description="Additional LLM observations")
