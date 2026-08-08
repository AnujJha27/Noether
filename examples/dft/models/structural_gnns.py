from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


def ring_adjacency(sites: int = 6) -> torch.Tensor:
    adjacency = torch.zeros((sites, sites), dtype=torch.bool)
    for site in range(sites):
        adjacency[site, (site - 1) % sites] = True
        adjacency[site, (site + 1) % sites] = True
    return adjacency


class StructuralRingGNN(nn.Module):
    """Small exportable model for structural certification demonstrations."""

    def __init__(self, *, depth: int = 3, operator: str = "symmetrized",
                 xc: str = "hinge") -> None:
        super().__init__()
        self.depth = depth
        self.operator = operator
        self.xc = xc
        self.register_buffer("adjacency", ring_adjacency())
        self.base_operator = nn.Parameter(torch.randn(6, 6))

    def forward(self, density: torch.Tensor):
        adjacency = self.adjacency.to(dtype=density.dtype)
        state = density
        for _ in range(self.depth):
            state = torch.matmul(adjacency, state)
        xc_energy = (
            F.relu(density.sum())
            if self.xc == "hinge"
            else torch.sigmoid(density.sum())
        )
        if self.operator == "symmetrized":
            learned_self_energy = self.base_operator + self.base_operator.T
        elif self.operator == "identity":
            learned_self_energy = torch.eye(
                6, dtype=density.dtype, device=density.device
            )
        elif self.operator == "zero":
            learned_self_energy = torch.zeros_like(self.base_operator)
        else:
            learned_self_energy = self.base_operator
        return xc_energy, learned_self_energy, state


def CertifiedRingGNN() -> StructuralRingGNN:
    return StructuralRingGNN(depth=3, operator="symmetrized", xc="hinge")


def TooShallowRingGNN() -> StructuralRingGNN:
    return StructuralRingGNN(depth=2, operator="symmetrized", xc="hinge")


def UnconstrainedOperatorGNN() -> StructuralRingGNN:
    return StructuralRingGNN(depth=3, operator="unconstrained", xc="hinge")


def SmoothXCGNN() -> StructuralRingGNN:
    return StructuralRingGNN(depth=3, operator="symmetrized", xc="smooth")


def IdentityOperatorRingGNN() -> StructuralRingGNN:
    return StructuralRingGNN(depth=3, operator="identity", xc="hinge")


def ZeroOperatorRingGNN() -> StructuralRingGNN:
    return StructuralRingGNN(depth=3, operator="zero", xc="hinge")


def AllFailuresRingGNN() -> StructuralRingGNN:
    return StructuralRingGNN(depth=2, operator="unconstrained", xc="smooth")
