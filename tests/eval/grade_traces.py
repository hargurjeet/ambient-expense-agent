import sys
import google.auth
from google.auth.credentials import AnonymousCredentials

# Mock google.auth.default to bypass Vertex AI GCP credential requirement
# since we evaluate custom metrics locally using AI Studio's GEMINI_API_KEY.
def mock_default(*args, **kwargs):
    return AnonymousCredentials(), "mock-project"

google.auth.default = mock_default

from google.agents.cli.eval.cmd_grade import cmd_grade

if __name__ == "__main__":
    # Remove script name and run the click CLI command
    cmd_grade(sys.argv[1:])
