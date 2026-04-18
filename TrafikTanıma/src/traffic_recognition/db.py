from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunSession(Base):
    __tablename__ = "run_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_path: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, default=lambda: dt.datetime.utcnow())
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)

    vehicle_tracks: Mapped[list["VehicleTrack"]] = relationship(back_populates="session")


class VehicleTrack(Base):
    __tablename__ = "vehicle_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("run_sessions.id"), nullable=False, index=True)
    track_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vehicle_type: Mapped[str] = mapped_column(String, nullable=False)
    first_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    best_plate_text: Mapped[str | None] = mapped_column(String, nullable=True)
    best_plate_conf: Mapped[float | None] = mapped_column(Float, nullable=True)

    session: Mapped[RunSession] = relationship(back_populates="vehicle_tracks")
    plate_reads: Mapped[list["PlateRead"]] = relationship(back_populates="vehicle_track")


class PlateRead(Base):
    __tablename__ = "plate_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("run_sessions.id"), nullable=False, index=True)
    vehicle_track_id: Mapped[int] = mapped_column(ForeignKey("vehicle_tracks.id"), nullable=False, index=True)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    plate_text: Mapped[str] = mapped_column(String, nullable=False)
    conf: Mapped[float] = mapped_column(Float, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)

    vehicle_track: Mapped[VehicleTrack] = relationship(back_populates="plate_reads")


def open_db(db_path: str):
    # sqlite:///absolute/path or sqlite:///relative
    if db_path.startswith("sqlite:"):
        url = db_path
    else:
        url = f"sqlite:///{db_path}"
    connect_args = {}
    if url.startswith("sqlite:"):
        # SQLite write contention için bekleme + WAL
        connect_args = {"timeout": 30, "check_same_thread": False}
    engine = create_engine(url, future=True, connect_args=connect_args)

    if url.startswith("sqlite:"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=30000;")
            finally:
                cursor.close()

    Base.metadata.create_all(engine)
    return engine


@dataclass
class TrackUpsert:
    session_id: int
    track_id: int
    vehicle_type: str
    frame_index: int


def upsert_vehicle_track(db: Session, up: TrackUpsert) -> VehicleTrack:
    existing = db.scalar(
        select(VehicleTrack).where(
            VehicleTrack.session_id == up.session_id,
            VehicleTrack.track_id == up.track_id,
        )
    )
    if existing is None:
        existing = VehicleTrack(
            session_id=up.session_id,
            track_id=up.track_id,
            vehicle_type=up.vehicle_type,
            first_frame=up.frame_index,
            last_frame=up.frame_index,
        )
        db.add(existing)
        db.flush()
        return existing

    existing.last_frame = up.frame_index
    if existing.vehicle_type != up.vehicle_type:
        # model türü değişebiliyor; ilkini tutmak yerine daha sık görüleni hesaplamak için ayrı sayaç gerek.
        # şimdilik en son görüleni yaz.
        existing.vehicle_type = up.vehicle_type
    return existing


def insert_plate_read(
    db: Session,
    *,
    session_id: int,
    vehicle_track_id: int,
    frame_index: int,
    plate_text: str,
    conf: float,
    image_path: str | None,
) -> PlateRead:
    pr = PlateRead(
        session_id=session_id,
        vehicle_track_id=vehicle_track_id,
        frame_index=frame_index,
        plate_text=plate_text,
        conf=conf,
        image_path=image_path,
    )
    db.add(pr)
    return pr


def update_best_plate(db: Session, vehicle_track: VehicleTrack, plate_text: str, conf: float) -> None:
    if vehicle_track.best_plate_conf is None or conf > vehicle_track.best_plate_conf:
        vehicle_track.best_plate_text = plate_text
        vehicle_track.best_plate_conf = conf
