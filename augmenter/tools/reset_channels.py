"""Сбросить ВСЕ каналы: склад аугментера + каналы на нодах (агенты ofnode и
старая нода по SSH). После рестарта аугментера reconcile заведёт каналы заново —
с текущими настройками. Без --yes только показывает, что будет снесено.

    docker exec -i augmenter python - < /root/reset_channels.py          # посмотреть
    docker exec -i augmenter python - --yes < /root/reset_channels.py    # снести
    docker restart augmenter                                              # завести заново

Доски и volga-доки на аккаунте оператора НЕ удаляет (их чистить руками).
"""
import asyncio
import json
import sys

import accounts
import nodeapi
import nodes
import provisioner as p
import store

YES = "--yes" in sys.argv


def sources():
    """Где могут жить каналы: (название, список(), снять(канал))."""
    out = []
    if p.NODES:
        node = p.NODES[0]

        async def ssh_list():
            res = await p._ssh(node, f"sh {p.NODE_INSTALL_REMOTE} list")
            return [c["channel"] for c in json.loads(res.strip().splitlines()[-1]).get("channels", [])]

        async def ssh_remove(ch):
            await p._ssh(node, f"sh {p.NODE_INSTALL_REMOTE} remove {ch}")

        out.append((f"{node} (SSH)", ssh_list, ssh_remove))
    for n in nodes.all():
        async def agent_list(n=n):
            return [c["channel"] for c in await nodeapi.channels(n)]

        async def agent_remove(ch, n=n):
            await nodeapi.remove(n, ch)

        out.append((f"агент {n.name} ({n.address}:{n.port})", agent_list, agent_remove))
    return out


async def listing(src):
    found = {}
    for name, lst, _ in src:
        try:
            found[name] = await lst()
        except Exception as error:  # нода не отвечает — покажем и пойдём дальше
            print(f"  ! {name}: {error}")
            found[name] = []
    return found


async def main() -> None:
    if p.STUB:
        sys.exit("PROVISION_MODE не real — сбрасывать нечего")
    src = sources()
    if not src:
        sys.exit("нет ни одной ноды (ни агентов, ни OPENFLUX_NODES)")
    users = sorted(store.keys())
    mine = {p._channel(su) for su in users}
    print(f"склад: {len(users)} юзер(ов): " + (", ".join(f"{su} → {p._channel(su)}" for su in users) or "—"))
    for name, chans in (await listing(src)).items():
        print(f"{name}: {len(chans)} канал(ов): "
              + (", ".join(ch + ("" if ch in mine else " (не из склада)") for ch in chans) or "—"))
    print(f"пул: {accounts.stats()}")
    if not YES:
        print("\nэто проба, ничего не тронуто. Снести всё — тот же запуск с --yes")
        return

    for su in users:
        try:
            await p.deprovision(su)  # с той ноды, где канал живёт + ёмкость аккаунту
            print(f"  - {su}: канал {p._channel(su)} снят")
        except Exception as error:  # канала уже нет — не беда
            print(f"  ! {su}: {error}")
        store.delete(su)
    for name, chans in (await listing(src)).items():  # остатки, которых нет в складе
        remove = next(r for n, _, r in src if n == name)
        for ch in chans:
            try:
                await remove(ch)
                print(f"  - {ch} на {name}: снят (не из склада)")
            except Exception as error:
                print(f"  ! {ch} на {name}: {error}")
    with accounts._lock:  # каналов не осталось — обнуляем счётчики пула
        accounts._conn.execute("UPDATE accounts SET active_docs = 0")
        accounts._conn.execute("DELETE FROM channel_accounts")
        accounts._conn.commit()
    with nodes._lock:
        nodes._conn.execute("DELETE FROM channel_nodes")
        nodes._conn.commit()
    left = sum(len(c) for c in (await listing(src)).values())
    print(f"\nготово: в складе {len(store.keys())}, на нодах {left} канал(ов), пул {accounts.stats()}")
    print("дальше: docker restart augmenter — reconcile заведёт каналы заново")


asyncio.run(main())
