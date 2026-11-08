"""PDDikti SDK Neo Feeder - Python SDK & Web Service Client untuk Neo Feeder PDDIKTI Kampus."""

from pddikti_feeder.client import (
    AsyncNeoFeederClient,
    NeoFeederClient,
)
from pddikti_feeder.exceptions import (
    FeederAuthError,
    FeederConnectionError,
    FeederException,
)
from pddikti_feeder.models import (
    DosenFeeder,
    FeederResponse,
    MahasiswaFeeder,
    ProfilPerguruanTinggiFeeder,
    ProgramStudiFeeder,
)

__version__ = "0.1.0"
__all__ = [
    "NeoFeederClient",
    "AsyncNeoFeederClient",
    "FeederException",
    "FeederAuthError",
    "FeederConnectionError",
    "FeederResponse",
    "ProfilPerguruanTinggiFeeder",
    "ProgramStudiFeeder",
    "MahasiswaFeeder",
    "DosenFeeder",
    "__version__",
]
