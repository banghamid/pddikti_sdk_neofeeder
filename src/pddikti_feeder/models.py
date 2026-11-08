"""Model data dan schema respon untuk Neo Feeder PDDIKTI."""

from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class FeederResponse(BaseModel, Generic[T]):
    """Struktur dasar respon JSON-RPC dari Neo Feeder Web Service."""
    model_config = ConfigDict(extra="ignore")

    error_code: int = 0
    error_desc: str = ""
    data: Optional[T] = None

    @property
    def is_success(self) -> bool:
        return self.error_code == 0


class ProfilPerguruanTinggiFeeder(BaseModel):
    """Informasi profil perguruan tinggi dari fungsi GetProfilPT."""
    model_config = ConfigDict(extra="ignore")

    id_perguruan_tinggi: Optional[str] = None
    kode_perguruan_tinggi: Optional[str] = None
    nama_perguruan_tinggi: Optional[str] = None
    telepon: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    jalan: Optional[str] = None
    wilayah: Optional[str] = None
    status: Optional[str] = None


class ProgramStudiFeeder(BaseModel):
    """Informasi program studi dari fungsi GetProdi."""
    model_config = ConfigDict(extra="ignore")

    id_prodi: Optional[str] = None
    kode_program_studi: Optional[str] = None
    nama_program_studi: Optional[str] = None
    status: Optional[str] = None
    nama_jenjang_pendidikan: Optional[str] = None


class MahasiswaFeeder(BaseModel):
    """Data mahasiswa dari fungsi GetBiodataMahasiswa atau GetListMahasiswa."""
    model_config = ConfigDict(extra="ignore")

    id_mahasiswa: Optional[str] = None
    nama_mahasiswa: str
    jenis_kelamin: Optional[str] = None
    tempat_lahir: Optional[str] = None
    tanggal_lahir: Optional[str] = None
    nama_ibu_kandung: Optional[str] = None
    nik: Optional[str] = None
    nisn: Optional[str] = None


class DosenFeeder(BaseModel):
    """Data dosen dari fungsi GetDosen."""
    model_config = ConfigDict(extra="ignore")

    id_dosen: Optional[str] = None
    nama_dosen: str
    nidn: Optional[str] = None
    nip: Optional[str] = None
    jenis_kelamin: Optional[str] = None
    id_status_aktif: Optional[str] = None
    nama_status_aktif: Optional[str] = None
