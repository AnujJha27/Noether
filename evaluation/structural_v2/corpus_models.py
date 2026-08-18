"""Controlled Torch-exportable artifacts for the frozen VISTA Structural V2 corpus."""
from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


def _adjacency(kind: str, sites: int) -> torch.Tensor:
    value = torch.zeros((sites, sites), dtype=torch.bool)
    if kind == "chain":
        for source in range(sites - 1): value[source + 1, source] = True
    elif kind == "ring":
        for source in range(sites): value[(source + 1) % sites, source] = True
    else:
        for source, target in ((0, 1), (1, 3), (3, 2), (2, 4), (4, 0)):
            if source < sites and target < sites: value[target, source] = True
    return value


class CorpusModel(nn.Module):
    def __init__(self, *, topology="ring", sites=5, depth=3, message="plain",
                 operator="symmetrized", xc="relu") -> None:
        super().__init__()
        self.depth, self.message, self.operator, self.xc = depth, message, operator, xc
        self.register_buffer("adjacency", _adjacency(topology, sites))
        self.base = nn.Parameter(torch.randn(sites, sites))
        self.other = nn.Parameter(torch.randn(sites, sites))

    def forward(self, density: torch.Tensor):
        adjacency = self.adjacency.to(dtype=density.dtype)
        state = density
        irrelevant = density.sum() * 0
        for index in range(self.depth):
            state = torch.matmul(adjacency, state)
            if self.message == "nonlinear" and index + 1 < self.depth:
                state = F.relu(state)
        if self.message == "alias":
            alias = adjacency.contiguous()
            state = torch.matmul(alias, state)
        if self.message == "irrelevant":
            irrelevant = torch.matmul(self.other, self.other).sum() * 0
        if self.xc == "relu": xc = F.relu(density.sum() + irrelevant)
        elif self.xc == "leaky": xc = F.leaky_relu(density.sum())
        elif self.xc == "sigmoid": xc = torch.sigmoid(density.sum())
        elif self.xc == "tanh": xc = torch.tanh(density.sum())
        elif self.xc == "none": xc = density.sum()
        elif self.xc == "mixed": xc = torch.sigmoid(F.relu(density.sum()))
        else: xc = torch.sin(density.sum())
        if self.operator == "symmetrized": operator = self.base + self.base.T
        elif self.operator == "zero": operator = torch.zeros_like(self.base)
        elif self.operator == "identity": operator = torch.eye(self.base.shape[0], dtype=density.dtype, device=density.device)
        elif self.operator == "cross": operator = self.base + self.other.T
        elif self.operator == "indirect": operator = self.base + self.base.T.clone()
        elif self.operator == "free": operator = self.base
        elif self.operator == "nested": operator = self.base + (self.base.T + self.base.T)
        elif self.operator == "transformed": operator = self.base + 2 * self.base.T
        else: operator = self.base @ self.base.T
        return xc, operator, state


def make_model(spec: dict) -> CorpusModel:
    return CorpusModel(**spec)
