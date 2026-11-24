import logging

# Provider request URLs can contain private endpoints and query parameters.
logging.getLogger("httpx").setLevel(logging.WARNING)
