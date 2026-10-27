"""Ordered application index with expected O(log n) updates."""
from random import Random


class Node:
    def __init__(self, key, student, priority):
        self.key, self.student, self.priority = key, student, priority
        self.left = self.right = None
        self.size = 1


def size(node):
    return node.size if node else 0


def refresh(node):
    node.size = 1 + size(node.left) + size(node.right)
    return node


def split(node, key):
    if node is None:
        return None, None
    if node.key < key:
        node.right, right = split(node.right, key)
        return refresh(node), right
    left, node.left = split(node.left, key)
    return left, refresh(node)


def merge(left, right):
    if left is None or right is None:
        return left or right
    if left.priority < right.priority:
        left.right = merge(left.right, right)
        return refresh(left)
    right.left = merge(left, right.left)
    return refresh(right)


def erase(node, key):
    if node is None:
        raise KeyError(key)
    if node.key == key:
        return merge(node.left, node.right)
    if key < node.key:
        node.left = erase(node.left, key)
    else:
        node.right = erase(node.right, key)
    return refresh(node)


class RankingIndex:
    """Unique keys are validated by UniversityEngine before insertion.

    Treap shape is randomized; ranking order always follows the supplied key.
    Bounds are expected, not worst-case guarantees. Use an iterative balanced
    tree or a database B-tree for adversarial inputs and production hardening.
    """
    def __init__(self):
        self.root = None
        self.random = Random(20261020)

    def add(self, key, student):
        left, right = split(self.root, key)
        node = Node(key, student, self.random.getrandbits(128))
        self.root = merge(merge(left, node), right)

    def remove(self, key):
        self.root = erase(self.root, key)

    def page(self, offset=0, limit=50):
        if type(offset) is not int or type(limit) is not int:
            raise ValueError("Integer pagination required")
        if offset < 0 or limit < 0:
            raise ValueError("Non-negative pagination required")
        result = []
        end = offset + limit
        def visit(node, start):
            if node is None or start >= end:
                return
            if start + node.size <= offset:
                return
            position = start + size(node.left)
            visit(node.left, start)
            if offset <= position < end:
                result.append((position + 1, node.student))
            visit(node.right, position + 1)
        visit(self.root, 0)
        return tuple(result)
