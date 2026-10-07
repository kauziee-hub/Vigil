"""Relational Graph Attention Network in plain torch (no torch_geometric).

Two relations, because direction matters for mules (collect vs distribute):
  'in'  : messages from senders to the recipient      (edge s -> d, message s -> d)
  'out' : messages from recipients back to the sender (edge s -> d, message d -> s)
Each relation has its own projection and attention vectors (edge-softmax over the node's incoming
messages, self-loop included); outputs are summed with a self projection, ELU, two layers, linear head.
Inputs are the shared windowed features (vigil/intel/features.py) after log1p + a scaler fitted on
TRAINING worlds only (audit A7). Serving uses the numpy port in vigil/intel/models.py::gat_forward.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

RELATIONS = ("in", "out")


class RelGATLayer(nn.Module):
    def __init__(self, din: int, dout: int, heads: int) -> None:
        super().__init__()
        self.heads, self.dh = heads, dout // heads
        self.self_lin = nn.Linear(din, dout)
        self.lin = nn.ModuleDict({r: nn.Linear(din, dout, bias=False) for r in RELATIONS})
        self.asrc = nn.ParameterDict({r: nn.Parameter(torch.empty(heads, self.dh)) for r in RELATIONS})
        self.adst = nn.ParameterDict({r: nn.Parameter(torch.empty(heads, self.dh)) for r in RELATIONS})
        for r in RELATIONS:
            nn.init.xavier_uniform_(self.asrc[r])
            nn.init.xavier_uniform_(self.adst[r])

    def forward(self, h: torch.Tensor, edges: dict[str, tuple[torch.Tensor, torch.Tensor]]) -> torch.Tensor:
        n = h.shape[0]
        out = self.self_lin(h)
        for r in RELATIONS:
            j, i = edges[r]
            z = self.lin[r](h).view(n, self.heads, self.dh)
            e = F.leaky_relu((z[i] * self.adst[r]).sum(-1) + (z[j] * self.asrc[r]).sum(-1), 0.2)
            idx = i.unsqueeze(1).expand(-1, self.heads)
            emax = torch.full((n, self.heads), float("-inf")).scatter_reduce(0, idx, e, reduce="amax", include_self=True)
            ex = torch.exp(e - emax.detach()[i])
            den = torch.zeros(n, self.heads).index_add(0, i, ex)
            alpha = ex / den[i]
            m = torch.zeros(n, self.heads, self.dh).index_add(0, i, alpha.unsqueeze(-1) * z[j])
            out = out + m.reshape(n, -1)
        return out


class FraudGAT(nn.Module):
    def __init__(self, din: int, hidden: int = 32, heads: int = 4, dropout: float = 0.1) -> None:
        super().__init__()
        self.heads = heads
        self.l1 = RelGATLayer(din, hidden, heads)
        self.l2 = RelGATLayer(hidden, hidden, heads)
        self.head = nn.Linear(hidden, 1)
        self.dropout = dropout

    def forward(self, x: torch.Tensor, edges: dict[str, tuple[torch.Tensor, torch.Tensor]]) -> torch.Tensor:
        h = F.dropout(F.elu(self.l1(x, edges)), self.dropout, self.training)
        h = F.dropout(F.elu(self.l2(h, edges)), self.dropout, self.training)
        return self.head(h).squeeze(-1)          # logits


def export(model: FraudGAT) -> dict:
    """Weights as numpy arrays named for vigil.intel.models.gat_forward."""
    out = {"heads": __import__("numpy").array(model.heads)}
    for k, layer in ((1, model.l1), (2, model.l2)):
        out[f"l{k}_self_w"] = layer.self_lin.weight.detach().numpy().T.astype("float64")
        out[f"l{k}_self_b"] = layer.self_lin.bias.detach().numpy().astype("float64")
        for r in RELATIONS:
            out[f"l{k}_{r}_w"] = layer.lin[r].weight.detach().numpy().T.astype("float64")
            out[f"l{k}_{r}_asrc"] = layer.asrc[r].detach().numpy().astype("float64")
            out[f"l{k}_{r}_adst"] = layer.adst[r].detach().numpy().astype("float64")
    out["out_w"] = model.head.weight.detach().numpy().T.astype("float64")
    out["out_b"] = model.head.bias.detach().numpy().astype("float64")
    return out
