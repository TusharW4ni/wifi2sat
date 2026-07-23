# Geometry-Decorrelation of GNSS Carrier-Phase Gestures — Theory

**Project:** GNSS-based gesture recognition (FineSat-style), u-blox EVK-F9P
**Question this derivation answers:** _How long is the time window over which the same hand gesture, performed in front of a fixed antenna, produces a reproducible carrier-phase signal — given that the satellite geometry drifts continuously?_

The headline theoretical result is that the window is governed by a single dimensionless curvature **κ** that depends on the **shape of the gesture**, and that **single-axis gestures are geometrically robust (κ → 0) while multi-axis gestures decorrelate quadratically with geometry drift.**

---

## 1. Setup and signal model

A hand moves near a fixed GNSS antenna, acting as a moving multipath reflector. The antenna does **not** translate; the gesture is the motion of the reflector. Let

- $\mathbf{d}(t) \in \mathbb{R}^3$ — the hand displacement trajectory (the gesture), defined over a short window $t \in [0, T_g]$ (a few seconds),
- $\hat{\mathbf{e}}_i$ — the line-of-sight (LOS) unit vector from antenna to satellite $i$,
- $\lambda$ — the carrier wavelength.

To leading order, the multipath-induced carrier-phase perturbation on satellite $i$ is proportional to the projection of the hand displacement onto the LOS direction:

$$
\phi_i(t) \;\approx\; \frac{2\pi}{\lambda}\,\hat{\mathbf{e}}_i \cdot \mathbf{d}(t) \;+\; \underbrace{c(t)}_{\text{rx clock}} \;+\; \underbrace{\rho_i(t)}_{\text{geometric range trend}} \;+\; \text{noise}.
$$

**Single-differencing** against a reference satellite removes the receiver clock $c(t)$ (common to all satellites), and a low-order **detrend** over the window removes the smooth geometric range trend $\rho_i(t)$. What remains is the gesture signal:

$$
\boxed{\,s_i(t) \;=\; \mathbf{g}_i \cdot \mathbf{d}(t)\,}, \qquad
\mathbf{g}_i \;=\; \frac{2\pi}{\lambda}\big(\hat{\mathbf{e}}_i - \hat{\mathbf{e}}_{\text{ref}}\big).
$$

$\mathbf{g}_i$ is the **differential LOS sensitivity vector**. The whole geometry of the problem enters through these vectors.

> **Model caveat (established empirically).** The LOS-projection model is leading-order. Real specular reflection off the hand carries reflection-geometry factors (the sensitivity is along the bisector of incident/reflected rays, not pure LOS), and the antenna phase-center variation is not captured. In our data, a pure 3-D translation model explained ~69 % of the push variance but only ~39 % of the star variance, so the model below is a first-order description, not exact.

---

## 2. Correlation under geometry drift

Perform the _same_ gesture $\mathbf{d}(t)$ at two times A and B separated by $\Delta t$. Between them the LOS rotates, so $\mathbf{g}_i^A \to \mathbf{g}_i^B$. The reproducibility of satellite $i$'s signal is the normalized zero-lag correlation over the window:

$$
r \;=\; \frac{\langle s_A, s_B\rangle}{\lVert s_A\rVert\,\lVert s_B\rVert}
   \;=\; \frac{\int_0^{T_g} (\mathbf{g}_A\!\cdot\mathbf{d})(\mathbf{g}_B\!\cdot\mathbf{d})\,dt}
              {\sqrt{\int (\mathbf{g}_A\!\cdot\mathbf{d})^2 dt}\,\sqrt{\int (\mathbf{g}_B\!\cdot\mathbf{d})^2 dt}}.
$$

Each inner product is a quadratic form in the **gesture structure matrix** (the $3\times3$ second-moment / scatter matrix of the trajectory):

$$
\boxed{\,M \;=\; \int_0^{T_g} \mathbf{d}(t)\,\mathbf{d}(t)^{\!\top}\,dt\,}
\qquad\Longrightarrow\qquad
\int (\mathbf{g}_A\!\cdot\mathbf{d})(\mathbf{g}_B\!\cdot\mathbf{d})\,dt = \mathbf{g}_A^{\!\top} M\,\mathbf{g}_B .
$$

So the correlation is the **generalized cosine** between the two geometry vectors in the metric $M$:

$$
r \;=\; \frac{\mathbf{g}_A^{\!\top} M\,\mathbf{g}_B}
              {\sqrt{\mathbf{g}_A^{\!\top} M\,\mathbf{g}_A}\,\sqrt{\mathbf{g}_B^{\!\top} M\,\mathbf{g}_B}}.
$$

The entire dependence on the **gesture shape** is in $M$; the entire dependence on **geometry drift** is in $\mathbf{g}_A \to \mathbf{g}_B$.

---

## 3. Small-drift expansion → the curvature κ

Write the drift as $\mathbf{g}_B = \mathbf{g}_A + \Delta\mathbf{g}$ with $\Delta\mathbf{g}$ small. Define the three scalars

$$
a = \mathbf{g}_A^{\!\top} M\,\mathbf{g}_A,\qquad
b = \mathbf{g}_A^{\!\top} M\,\Delta\mathbf{g},\qquad
c = \Delta\mathbf{g}^{\!\top} M\,\Delta\mathbf{g}.
$$

Then $r = \dfrac{a+b}{\sqrt{a}\,\sqrt{a+2b+c}} = \dfrac{1+\beta}{\sqrt{1+2\beta+\gamma}}$ with $\beta=b/a$ (order $\Delta\theta$) and $\gamma=c/a$ (order $\Delta\theta^2$). Expanding to second order:

$$
\sqrt{1+2\beta+\gamma} \approx 1 + \beta + \tfrac{\gamma}{2} - \tfrac{\beta^2}{2},
\qquad
r \approx (1+\beta)\!\left(1 - \beta - \tfrac{\gamma}{2} + \tfrac{3\beta^2}{2}\right)
   = 1 - \tfrac{1}{2}\big(\gamma - \beta^2\big).
$$

Therefore

$$
1 - r \;\approx\; \frac{1}{2}\,\frac{c\,a - b^2}{a^2}.
$$

The LOS rotates by a small angle $\Delta\theta$, so $\Delta\mathbf{g} = \Delta\theta\,\mathbf{w}$ where $\mathbf{w} = d\mathbf{g}/d\theta$ is fixed by the geometry. Substituting $b=\Delta\theta\,(\mathbf{g}^{\!\top}M\mathbf{w})$ and $c=\Delta\theta^2(\mathbf{w}^{\!\top}M\mathbf{w})$:

$$
\boxed{\,r \;\approx\; 1 - \tfrac{1}{2}\,\kappa\,\Delta\theta^2\,},
\qquad
\boxed{\,\kappa \;=\; \frac{(\mathbf{w}^{\!\top}M\mathbf{w})(\mathbf{g}^{\!\top}M\mathbf{g}) - (\mathbf{g}^{\!\top}M\mathbf{w})^2}{(\mathbf{g}^{\!\top}M\mathbf{g})^2}\,}.
$$

$\kappa$ is dimensionless and is the **decorrelation curvature**.

### 3.1 Properties of κ

- **Non-negativity.** By the Cauchy–Schwarz inequality in the $M$-inner-product, $(\mathbf{g}^{\!\top}M\mathbf{w})^2 \le (\mathbf{g}^{\!\top}M\mathbf{g})(\mathbf{w}^{\!\top}M\mathbf{w})$, so $\kappa \ge 0$ always. Correlation can only decrease with drift.
- **κ = 0 condition.** $\kappa = 0$ iff $M\mathbf{w} \parallel M\mathbf{g}$, i.e. the drift direction is indistinguishable from the original direction _as seen through the gesture metric $M$_.

---

## 4. The headline result: gesture rank sets the window

### 4.1 Single-axis gesture → κ = 0 (geometry-robust)

If the gesture is one-dimensional, $\mathbf{d}(t) = f(t)\,\hat{\mathbf{n}}$ for a fixed direction $\hat{\mathbf{n}}$, then

$$
M = \Big(\!\int f^2\,dt\Big)\,\hat{\mathbf{n}}\hat{\mathbf{n}}^{\!\top} \quad(\text{rank 1}).
$$

For any vector $\mathbf{x}$, $M\mathbf{x} = (\int f^2)(\hat{\mathbf{n}}\cdot\mathbf{x})\,\hat{\mathbf{n}}$ — always parallel to $\hat{\mathbf{n}}$. Hence $M\mathbf{g} \parallel M\mathbf{w}$, and substituting into κ:

$$
\kappa_{\text{1D}} = \frac{(\int f^2)^2\big[(\hat{\mathbf{n}}\cdot\mathbf{w})^2(\hat{\mathbf{n}}\cdot\mathbf{g})^2 - (\hat{\mathbf{n}}\cdot\mathbf{g})^2(\hat{\mathbf{n}}\cdot\mathbf{w})^2\big]}{(\int f^2)^2(\hat{\mathbf{n}}\cdot\mathbf{g})^4} = 0.
$$

**A single-axis gesture has no second-order geometric decorrelation.** Intuition: a 1-D gesture senses only the scalar projection $\hat{\mathbf{n}}\cdot\mathbf{g}$. As geometry drifts, that projection changes _amplitude_ but the signal _shape_ $f(t)$ is unchanged — and correlation is amplitude-invariant. The window is then limited by reproducibility and higher-order terms, not geometry.

### 4.2 Multi-axis gesture → κ > 0 (tighter window)

If $\mathbf{d}(t)$ explores two or three dimensions (a star, a circle), $M$ is full-rank with spread eigenvalues, $M\mathbf{g}$ and $M\mathbf{w}$ are generally not parallel, and $\kappa > 0$. The signal _shape_ — not just amplitude — changes with geometry, so correlation falls quadratically. The larger the eigenvalue spread of $M$ (the more genuinely multi-dimensional the gesture), the larger κ and the tighter the window.

### 4.3 Choice of probe gestures

We use two gestures at the κ-extremes so everything else interpolates between them:

| gesture  | character            | structure matrix eigenvalues (normalized) | κ   | window                     |
| -------- | -------------------- | ----------------------------------------- | --- | -------------------------- |
| **push** | near single-axis     | ≈ [1, 0.009, 0.008] (≈ rank-1)            | ≈ 0 | wide                       |
| **star** | genuinely multi-axis | ≈ [1, 0.34, 0.28]                         | > 0 | tight (binding constraint) |

(Eigenvalues are illustrative estimates; the operative values are the **empirical** $M$ measured from the recovered data.)

---

## 5. The usable window δt_max

Define the window by a minimum acceptable correlation $r_{\min}$:

$$
r_{\min} = 1 - \tfrac{1}{2}\kappa\,\Delta\theta_{\max}^2
\;\;\Longrightarrow\;\;
\Delta\theta_{\max} = \sqrt{\frac{2(1-r_{\min})}{\kappa}}.
$$

The differential LOS rotates at an apparent rate $\omega_{\text{LOS}}$, so $\Delta\theta = \omega_{\text{LOS}}\,\delta t$ and

$$
\boxed{\,\delta t_{\max} \;=\; \frac{1}{\omega_{\text{LOS}}}\sqrt{\frac{2(1-r_{\min})}{\kappa}}\,}.
$$

**Scaling consequences:**

- $\delta t_{\max} \propto \kappa^{-1/2}$. Push ($\kappa\to0$) → window limited by reproducibility, not geometry. Star (finite κ) → finite window.
- The push/star window ratio is $\sqrt{\kappa_{\text{star}}/\kappa_{\text{push}}}$, set entirely by the empirical $M$.
- $\omega_{\text{LOS}} \approx 0.45^{\circ}/\text{min}$ for GPS/BeiDou-MEO at this site (tightly clustered 0.42–0.52 across elevations, because the rate is dominated by orbital angular velocity, not elevation).

---

## 6. The reproducibility floor α (why mechanical reproduction matters)

At **zero** geometry drift, two free-hand repetitions are still not identical:

$$
r(\Delta\theta = 0) = \alpha < 1,
$$

the **reproducibility floor**, set by how precisely the human (or actuator) repeats the gesture, bounded above by the thermal/carrier-phase **noise ceiling** $r_{\max} \approx 0.85$. A useful combined model is

$$
r(\delta t) \;\approx\; \alpha\,\Big(1 - \tfrac{1}{2}\kappa\,\omega_{\text{LOS}}^2\,\delta t^2\Big).
$$

The geometric window is only **measurable** when $\alpha$ is high enough that the quadratic geometry term — not free-hand sloppiness — dominates the falloff. Our measurements gave provisional free-hand $\alpha \approx 0.6$ (single-differenced, recovered data), well below the ~0.85 ceiling — which is why characterizing the _geometric_ window requires **mechanically reproduced** gestures to isolate κ from human irreproducibility. The eventual free-hand product does not need signal correlation at all; it needs a classifier trained across geometry.

---

## 7. Geometry repeat (the direct measurement)

Rather than wait for natural drift, the geometry can be revisited. GPS/BeiDou-MEO geometry repeats every **sidereal** day:

$$
T_{\text{sid}} = 86164.0905\ \text{s} \quad(\approx \text{solar day} - 3\text{ m }56\text{ s}).
$$

- **GPS only:** geometry recurs at $T + k\,T_{\text{sid}}$ (1 sidereal day; ~3 m 56 s earlier each solar day).
- **GPS + BeiDou jointly:** GPS repeats in 1 sidereal day (2 orbits), BeiDou-MEO in 7 sidereal days (13 orbits); the **joint** constellation geometry repeats every **7 sidereal days** ($\approx T + 7\text{ d} - 27\text{ m }31\text{ s}$).

**Direct window measurement (the repeat-offset sweep):** collect a reference at $T$, then revisit at $T + T_{\text{sid}} + \varepsilon$ for a set of offsets $\varepsilon$. The induced drift is $\Delta\theta = \omega_{\text{LOS}}\,\varepsilon$, so sweeping $\varepsilon$ traces $r(\Delta\theta)$ directly and the measured falloff is compared against the predicted $1 - \tfrac12\kappa\Delta\theta^2$.

---

## 8. Summary of the theoretical result

1. The reproducible gesture signal is $s_i(t) = \mathbf{g}_i\cdot\mathbf{d}(t)$; correlation under drift is the $M$-metric cosine of the geometry vectors, $M = \int \mathbf{d}\mathbf{d}^{\!\top}dt$.
2. Decorrelation is quadratic: $r \approx 1 - \tfrac12\kappa\,\Delta\theta^2$ with the closed-form curvature $\kappa = \dfrac{(\mathbf{w}^{\!\top}M\mathbf{w})(\mathbf{g}^{\!\top}M\mathbf{g})-(\mathbf{g}^{\!\top}M\mathbf{w})^2}{(\mathbf{g}^{\!\top}M\mathbf{g})^2} \ge 0$.
3. **Single-axis gestures are geometry-robust** ($\kappa = 0$, rank-1 $M$); **multi-axis gestures decorrelate** ($\kappa > 0$). Gesture _shape_, via the rank/eigenvalue-spread of $M$, sets everything.
4. Window: $\delta t_{\max} = \omega_{\text{LOS}}^{-1}\sqrt{2(1-r_{\min})/\kappa}$, with $\omega_{\text{LOS}}\approx0.45^{\circ}/$min.
5. The measurement requires a reproducibility floor $\alpha$ near the noise ceiling; free-hand $\alpha\approx0.6$ means **mechanical reproduction** is needed to isolate the geometric κ. Direct verification is via the sidereal **repeat-offset sweep**.
