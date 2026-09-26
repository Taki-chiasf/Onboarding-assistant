from pydantic import BaseModel

# Document access is additive: a role carries the access of every role it sits
# above, so a more privileged identity never sees less of the corpus. Documents
# are tagged with the reader's roles, not with their seniority, which keeps a
# single role dimension in the ACL without a hierarchy inside the tag values.
ROLE_IMPLIES: dict[str, tuple[str, ...]] = {"admin": ("employee",)}


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


def effective_roles(role: str) -> tuple[str, ...]:
    """A role plus every role it grants, in order, without repeats.

    An unrecognized role grants only itself, so an identity the deployment does
    not know about reads exactly what its own role allows.
    """
    roles = [role]
    for granted in ROLE_IMPLIES.get(role, ()):
        if granted not in roles:
            roles.append(granted)
    return tuple(roles)
