"""COMEXIO Local constants."""
DOMAIN = "comexio_local"
INTEGRATION_VERSION = "0.3.6.3.6"
DEFAULT_HOST = ""  # user supplies their own COMEXIO host on first setup
DEFAULT_TCP_PORT = 1505
DEFAULT_HA_PUSH_URL = ""  # user supplies a reachable private HA IPv4 callback
CONF_ADMIN_USER = "admin_user"
CONF_ADMIN_PASSWORD = "admin_password"
CONF_HOST = "host"
CONF_TCP_PORT = "tcp_port"
CONF_PUSH_BASE = "push_base"
CONF_WEBHOOK_ID = "webhook_id"
MIN_REQUEST_GAP = 0.3
TIMEOUT = 6.0
