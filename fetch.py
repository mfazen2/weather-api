from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, date, timedelta
from collections.abc import Iterator
from pathlib import Path
import s3fs
from threading import Event
from enum import Enum, auto
import re
import shutil


NEXRAD_FILENAME_RE = re.compile(
    r"^"
    r"(?P<station>K[A-Z]{3})"
    r"(?P<date>\d{8})"
    r"_"
    r"(?P<time>\d{6})"
    r"_V\d{2}"
    r"$"
)

@dataclass(frozen=True, slots=True)
class FetchRequest:
    station: str
    start_utc: datetime
    end_utc: datetime
    network: str = "NEXRAD"


    #validate fields (primarily debug)
    def __post_init__(self) -> None:
        station = self.station.strip().upper()
        start_utc = self.start_utc
        end_utc = self.end_utc

      

        if not re.fullmatch(r"K[A-Z]{3}", station):
            raise ValueError(
                "Invalid station formatting : station ID must fit WSR-88D standards, i.e. KIND."
                )
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError(
                "Times must be timezone aware."
                )

        start_utc = start_utc.astimezone(timezone.utc)
        end_utc = end_utc.astimezone(timezone.utc)
        if end_utc <= start_utc:
            raise ValueError(
                "Invalid time : end_utc must be later than start_utc."
            )
        if self.network != "NEXRAD":
            """TODO"""
            raise ValueError(
                "This fetcher does not currently support this network."
            )
        object.__setattr__(self,"station", station)
        object.__setattr__(self, "start_utc", start_utc)
        object.__setattr__(self, "end_utc", end_utc)




class FetchStatus(Enum):
    PENDING = auto()
    DISCOVERING = auto()
    DOWNLOADING = auto()
    SUCCEEDED = auto()
    PARTIALLY_SUCCEEDED = auto()
    FAILED = auto()
    CANCELLED = auto()

@dataclass(frozen=True, slots=True)
class ScanReference:
    station: str
    timestamp_utc: datetime
    s3_key: str
    @property
    def source_uri(self) -> str:
        return f"s3://{self.s3_key}"

@dataclass(frozen=True, slots=True)
class DownloadedScan:
    station: str
    timestamp_utc: datetime
    s3_key: str
    local_path: Path
    byte_size: int
    network: str = "NEXRAD"
    source_format: str = "nexrad_level2"

    @property
    def source_uri(self) -> str:
        return f"s3://{self.s3_key}"

@dataclass(frozen=True, slots=True) 
class FailedScan:
    station: str
    source_uri: str | None
    stage: str
    message: str
    exception_type: str
    retriable: bool = True

@dataclass(frozen=True, slots=True)
class FetchResult:
    request: FetchRequest
    status: FetchStatus
    scans: tuple[DownloadedScan,...]
    failures: tuple[FailedScan,...]
    started_utc: datetime | None
    finished_utc: datetime | None



class S3FetchJob:
    def __init__(self, fetcher: S3Fetcher, request: FetchRequest) -> None:
        self._fetcher = fetcher
        self._request = request
        
        self._cancelled = Event()
        self._status = FetchStatus.PENDING
        self._downloaded: list[DownloadedScan] = []
        self._failures: list[FailedScan] = []

        self._started_utc: datetime| None = None #change when work begins
        self._finished_utc: datetime | None = None #change when work ends/cancels

    #initiate work using existing s3 filesystem opened when the app is started
    def run(self) -> FetchResult:
        if self._status is not FetchStatus.PENDING:
            raise RuntimeError(
                "This job has already been run."
            )
        self._started_utc = datetime.now(timezone.utc)

        try:
            self._status = FetchStatus.DISCOVERING
            references = self.discover()

        except Exception as exc:
            self.record_failure(stage="discover", exc=exc)
            self._status = FetchStatus.FAILED
            self._finished_utc = datetime.now(timezone.utc)
            return self.result()
        
        if self._cancelled.is_set():
            self._status = FetchStatus.CANCELLED
            self._finished_utc = datetime.now(timezone.utc)
            return self.result()
        
        if not references:
            self._failures.append(
                FailedScan(
                    station = self._request.station,
                    source_uri = None,
                    stage = "discover",
                    message = "No matching scans were found.",
                    exception_type = "NoScansFound",
                    retriable = True
                )
            )

            self._status = FetchStatus.FAILED
            self._finished_utc = datetime.now(timezone.utc)
            return self.result()
        
        self._status = FetchStatus.DOWNLOADING

        for reference in references:
            if self._cancelled.is_set():
                self._status = FetchStatus.CANCELLED
                break
            
            try:
                scan = self.download(reference)
                self._downloaded.append(scan)
            
            except Exception as exc:
                self.record_failure(
                    stage="download",
                    exc=exc,
                    reference=reference
                )
        
        if self._status is not FetchStatus.CANCELLED:
            if self._downloaded and self._failures:
                self._status = FetchStatus.PARTIALLY_SUCCEEDED
            elif self._downloaded:
                self._status = FetchStatus.SUCCEEDED
            else:
                self._status = FetchStatus.FAILED
        
        self._finished_utc = datetime.now(timezone.utc)
        return self.result()



    #cancel work
    def cancel(self) -> None:
        self._cancelled.set()
    #called when run completes
    def result(self) -> FetchResult:
        return FetchResult(
            request=self._request,
            status=self._status,
            scans=tuple(self._downloaded),
            failures=tuple(self._failures),
            started_utc=self._started_utc,
            finished_utc=self._finished_utc
        )

    #called by run() to search for individual scans
    def discover(self) -> list[ScanReference]:
        return self._fetcher.discover(self._request)
    #called by run if discover returns successfully, modifies self.scans when successful
    def download(
        self,
        reference: ScanReference
        ) -> DownloadedScan:
        return self._fetcher.download(reference)
    #called by download if failure occurs, modifies self.failures
    def record_failure(
        self,
        *,
        stage: str,
        exc: Exception,
        reference: ScanReference | None = None,
        retriable: bool = True
        ) -> None:
        self._failures.append(

            FailedScan(
                station=self._request.station,
                source_uri=(
                    reference.source_uri
                    if reference is not None
                    else None
                ),
                stage=stage,
                message=str(exc),
                exception_type=type(exc).__name__,
                retriable=retriable,
            )
        )
    

        
def utc_calendar_days(
    start_utc: datetime,
    end_utc: datetime,
) -> Iterator[date]:
    current = start_utc.date()
    final = end_utc.date()

    while current <= final:
        yield current
        current += timedelta(days=1)
    


#this is our actual API; S3Job is a single request, and the dataclasses are structured vehicles for our data & messages
class S3Fetcher:
    BUCKET = "unidata-nexrad-level2"


    @classmethod
    def _daily_prefix(
        cls,
        station: str,
        day: date,
    ) -> str:
        return (
            f"{cls.BUCKET}/"
            f"{day:%Y}/"
            f"{day:%m}/"
            f"{day:%d}/"
            f"{station}/"
        )

    @staticmethod
    def _parse_reference(key: str) -> ScanReference | None:
        #convert NEXRAD L2 S3 key into a ScanReference
        filename = key.rsplit("/", 1)[-1]

        match = NEXRAD_FILENAME_RE.fullmatch(filename)
        if match is None:
            return None
        
        station = match.group("station")

        timestamp_utc = datetime.strptime(
            match.group("date") + match.group("time"),
            "%Y%m%d%H%M%S",
        ).replace(tzinfo=timezone.utc)

        return ScanReference(
            station=station,
            timestamp_utc=timestamp_utc,
            s3_key=key
        )
        
    def __init__(self,cache_dir: Path) -> None:
        self._cache_dir = cache_dir.expanduser().resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        #initiate filesystem
        self._fs = s3fs.S3FileSystem(
            anon=True,
            client_kwargs={"region_name": "us-east-1"}
        )
    #get a list of all calendar days between start_utc and end_utc (inclusive)
    #build s3 prefixes
    #call self._fs.find(prefix) for each prefix, and cache the resulting filenames
    #convert timestamps into utc-formatted datetime values
    #return the resulting references sorted by timestamp
    def discover(
        self,
        request: FetchRequest
    ) -> list[ScanReference]:
        references: list[ScanReference] = []
        for day in utc_calendar_days(
            request.start_utc,
            request.end_utc
        ):
            prefix = self._daily_prefix(request.station, day)
            try:
                keys = self._fs.find(prefix)
            except FileNotFoundError:
                continue
            for key in keys:
                ref = self._parse_reference(key)

                if ref is None or ref.station != request.station:
                    continue

                if (
                    request.start_utc
                    <= ref.timestamp_utc
                    < request.end_utc
                ):
                    references.append(ref)
            

        return sorted(
            references,
            key = lambda ref: ref.timestamp_utc
        )


    def _local_path(
        self,
        reference: ScanReference
    ) -> Path:
        filename = reference.s3_key.rsplit("/", 1)[-1]
        return (
            self._cache_dir
            / reference.station
            / f"{reference.timestamp_utc:%Y}"
            / f"{reference.timestamp_utc:%m}"
            / f"{reference.timestamp_utc:%d}"
            / filename
        )
    #atomic cache write to a temporary file, then rename to the final path
    def download(
        self,
        reference: ScanReference
    ) -> DownloadedScan:
        dest = self._local_path(reference)
        dest.parent.mkdir(parents=True, exist_ok=True)

        remote_info = self._fs.info(reference.s3_key)
        expected_size = remote_info.get("size")
        #cache hit -> completed nonempty file is already locally present
        if dest.is_file() and dest.stat().st_size > 0 and (
        expected_size is None
        or dest.stat().st_size == expected_size
        ):
            return DownloadedScan(
                station=reference.station,
                timestamp_utc=reference.timestamp_utc,
                s3_key=reference.s3_key,
                local_path=dest,
                byte_size=dest.stat().st_size
            )
        
        #cache miss -> download from s3 and create partial

        part = dest.with_name(f".{dest.name}.part")

        #remove pre-existing partial file if it exists
        part.unlink(missing_ok=True)

        try:
            with self._fs.open(reference.s3_key, "rb") as src:
                with part.open("wb") as target:
                    shutil.copyfileobj(
                        src, 
                        target,
                        length=1024*1024
                        )
            byte_size = part.stat().st_size

            if byte_size <= 0:
                raise RuntimeError(
                    f"Downloaded an empty s3 obj: {reference.source_uri}"
                )

            #promote to DownloadedScan and return only after copy validation succeded
            part.replace(dest)

            return DownloadedScan(
                station=reference.station,
                timestamp_utc=reference.timestamp_utc,
                s3_key=reference.s3_key,
                local_path=dest,
                byte_size=byte_size
            )
        except Exception:
            part.unlink(missing_ok=True)
            raise
