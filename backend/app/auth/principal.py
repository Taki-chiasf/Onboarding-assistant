from pydantic import BaseModel


class Principal(BaseModel):
    sub: str
    email: str
    dept: str
    role: str


DEMO_PERSONAS: list[Principal] = [
    Principal(
        sub="alex-chen",
        email="alex.chen@demo.example",
        dept="Engineering",
        role="employee",
    ),
    Principal(
        sub="jordan-lee",
        email="jordan.lee@demo.example",
        dept="People",
        role="admin",
    ),
    Principal(
        sub="priya-sharma",
        email="priya.sharma@demo.example",
        dept="Finance",
        role="employee",
    ),
]
