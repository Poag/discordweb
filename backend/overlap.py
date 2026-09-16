"""Pairwise co-occurrence ("who was with whom") from interval data.

Both cogs log plain [start_time, end_time] sessions and leave it to the
consumer to join them into relationships - see the docstrings in
voicelog.py and gamelog.py. This module is that join: given a list of
sessions that all share some grouping key (the same voice channel, or the
same game), it computes total overlapping seconds for every pair of
distinct users, using a sweep line so cost tracks actual concurrency
rather than the total number of sessions.
"""
from collections import defaultdict
from itertools import combinations
from typing import Dict, Iterable, List, Tuple

Session = Tuple[int, int, int]  # (user_id, start_time, end_time)
PairSeconds = Dict[Tuple[int, int], int]


def pairwise_overlap_seconds(sessions: Iterable[Session]) -> PairSeconds:
    """Total overlapping seconds between every pair of users across sessions
    that are already known to share a grouping key (one channel, one game).

    Sessions for the same user never contribute overlap with themselves;
    duplicate/overlapping sessions for one user (e.g. a logging glitch) are
    deduplicated via a reference count rather than double-counted.
    """
    events: List[Tuple[int, int, int]] = []  # (time, delta, user_id)
    for user_id, start, end in sessions:
        if end <= start:
            continue
        events.append((start, 1, user_id))
        events.append((end, -1, user_id))
    # Process ends before starts at an identical timestamp (delta -1 sorts
    # before +1) so touching-but-not-overlapping sessions score zero.
    events.sort(key=lambda e: (e[0], e[1]))

    active_counts: Dict[int, int] = {}
    active_users: set = set()
    pair_seconds: PairSeconds = defaultdict(int)
    last_t = None

    for t, delta, user_id in events:
        if last_t is not None and t > last_t and len(active_users) >= 2:
            dt = t - last_t
            for a, b in combinations(sorted(active_users), 2):
                pair_seconds[(a, b)] += dt
        cnt = active_counts.get(user_id, 0) + delta
        if cnt > 0:
            active_counts[user_id] = cnt
            active_users.add(user_id)
        else:
            active_counts.pop(user_id, None)
            active_users.discard(user_id)
        last_t = t

    return dict(pair_seconds)


def merge_pair_seconds(*maps: PairSeconds) -> PairSeconds:
    total: PairSeconds = defaultdict(int)
    for m in maps:
        for pair, secs in m.items():
            total[pair] += secs
    return dict(total)


def intersect_interval_lists(a: List[Tuple[int, int, object]], b: List[Tuple[int, int, object]]):
    """Every overlap between two lists of (start, end, label) intervals,
    each already sorted by start and internally non-overlapping (true of
    one person's own voice sessions - can't be in two channels at once -
    and, in practice, their own game sessions too). Used to find "was
    playing game G while in voice channel C" windows: intersect one
    person's game sessions with their voice sessions.

    Standard two-pointer sweep (each pointer only advances past an
    interval once it can no longer overlap anything upcoming in the other
    list), so it's O(len(a) + len(b)) rather than the O(len(a) * len(b)) a
    naive all-pairs check would cost.

    Yields (start, end, a_label, b_label) for every overlapping pair.
    """
    i, j = 0, 0
    while i < len(a) and j < len(b):
        a_start, a_end, a_label = a[i]
        b_start, b_end, b_label = b[j]
        lo, hi = max(a_start, b_start), min(a_end, b_end)
        if lo < hi:
            yield (lo, hi, a_label, b_label)
        if a_end < b_end:
            i += 1
        else:
            j += 1
