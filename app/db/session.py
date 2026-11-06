from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request):
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield session
