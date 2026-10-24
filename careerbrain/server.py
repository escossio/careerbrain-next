"""Explicit construction of the identity API; the caller owns the runtime config."""

from .api import CareerBrainAPI, IdentityAPI
from .auth import AuthService, GoogleVerifier
from .ingestion import IngestionService
from .resume import EphemeralResumeStore, FilesystemResumeStore, BoundedPdfExtractor, ResumeService
from .mobile import MobileService
from .tts import TtsService
from .db import tenant_pool


def create_app(*, auth_conninfo: str, api_conninfo: str, web_client_id: str,
               presenter_client_ids: tuple[str, ...], ingest_conninfo: str,
               private_worker_conninfo: str, resume_directory: str = '') -> CareerBrainAPI:
    verifier = GoogleVerifier(web_client_id, presenter_client_ids)
    auth_pool = tenant_pool(auth_conninfo)
    try:
        api_pool = tenant_pool(api_conninfo)
        try:
            service = AuthService(auth_pool, api_pool, verifier)
            ingest_pool = tenant_pool(ingest_conninfo)
            try:
                ingestion = IngestionService(ingest_pool)
                worker_pool = tenant_pool(private_worker_conninfo)
                try:
                    store = FilesystemResumeStore(resume_directory) if resume_directory else EphemeralResumeStore()
                    resume = ResumeService(api_pool, worker_pool, store, extractor=BoundedPdfExtractor())
                    mobile_pool = tenant_pool(api_conninfo)
                    try:
                        return CareerBrainAPI(IdentityAPI(service), ingestion, resume, MobileService(mobile_pool), TtsService())
                    except BaseException:
                        mobile_pool.close()
                        raise
                except BaseException:
                    worker_pool.close()
                    raise
            except BaseException:
                ingest_pool.close()
                raise
        except BaseException:
            api_pool.close()
            raise
    except BaseException:
        auth_pool.close()
        raise
