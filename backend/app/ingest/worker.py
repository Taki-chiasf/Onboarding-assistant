import os

import redis
from rq import Queue, Worker


def main() -> None:
    conn = redis.from_url(os.environ["REDIS_URL"])
    queue = Queue("default", connection=conn)
    worker = Worker([queue], connection=conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
