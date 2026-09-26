"""A two-parameter logistic (2PL) item response theory model, fit with PyTorch.

    P(right | student i, question j) = 1 / (1 + exp(-a_j (theta_i - b_j)))

theta is each student's ability, b each question's difficulty, and a its
discrimination. The fit is a joint MAP estimate: maximum likelihood with
weak priors (theta ~ N(0, 1), log a ~ N(0, 0.5^2), b ~ N(0, 2^2)), which fix
the scale and keep estimates finite for students who got everything right or
wrong. It's used to check that the simulated classes behave like the model says,
and to compare IRT parameters with the classical statistics.

Joint MAP shrinks abilities toward the prior mean when each student answers only
a few questions (with 20 questions, the fitted abilities' spread came out at
about 0.3 instead of 1), and the discriminations grow to compensate. The model
can't tell those apart, since only a(theta - b) matters. So after fitting, the
abilities are rescaled to mean 0 and SD 1, the scale the model assumes, and a
and b are converted to match (`standardize=True`). This changes the scale only,
not the fit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class IRTFit:
    a: np.ndarray
    b: np.ndarray
    theta: np.ndarray
    loss: float


def fit_2pl(responses: np.ndarray, epochs: int = 1500, lr: float = 0.05, seed: int = 0,
            standardize: bool = True) -> IRTFit:
    """Fit the 2PL model to a students × questions matrix of 0/1 (NaN = missing)."""
    import torch

    torch.manual_seed(seed)
    data = torch.tensor(np.asarray(responses, dtype=np.float32))
    observed = ~torch.isnan(data)
    target = torch.nan_to_num(data)
    n_students, n_items = data.shape

    theta = torch.zeros(n_students, requires_grad=True)
    log_a = torch.zeros(n_items, requires_grad=True)
    b = torch.zeros(n_items, requires_grad=True)
    optimizer = torch.optim.Adam([theta, log_a, b], lr=lr)
    bce = torch.nn.BCEWithLogitsLoss(reduction="none")

    for _ in range(epochs):
        optimizer.zero_grad()
        logits = log_a.exp() * (theta[:, None] - b[None, :])
        nll = (bce(logits, target) * observed).sum()
        prior = 0.5 * (theta ** 2).sum() + 0.5 * ((log_a / 0.5) ** 2).sum() + 0.5 * ((b / 2) ** 2).sum()
        loss = nll + prior
        loss.backward()
        optimizer.step()

    a_hat = log_a.exp().detach().numpy().astype(float)
    b_hat = b.detach().numpy().astype(float)
    theta_hat = theta.detach().numpy().astype(float)
    if standardize and theta_hat.std() > 0:
        # a (theta - b) is unchanged by theta -> (theta - m) / s, b -> (b - m) / s, a -> a s.
        m, s = theta_hat.mean(), theta_hat.std()
        theta_hat, b_hat, a_hat = (theta_hat - m) / s, (b_hat - m) / s, a_hat * s
    return IRTFit(a=a_hat, b=b_hat, theta=theta_hat, loss=float(loss.detach()))
