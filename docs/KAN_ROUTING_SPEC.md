# Kolmogorov-Arnold Network (KAN) Routing Specification & Auditability Guide
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Status:** Approved Specification  

---

## 1. Introduction & Theoretical Foundations

### 1.1 The Black-Box Problem in Edge Scheduling
Traditional machine learning load balancers and Kubernetes autoscalers (such as HPA, KEDA, or heuristic linear schedulers) exhibit severe shortcomings when deployed on shared edge devices like Point-of-Sale (POS) cash registers:
1. **Scalar-Blindness:** Heuristics rely on crude static thresholds (e.g., `CPU > 75%`), which fail to capture the non-linear interplay between GPU shared memory bandwidth, transaction burst rates, thermal throttling, and payload complexity.
2. **The "Black-Box" Deficit:** Multi-Layer Perceptrons (MLPs) can model non-linear boundaries, but their internal weights and matrix multiplications are completely uninterpretable. If a store generates \$15,000 in cloud GPU bills over a weekend, executive leadership and retail CFOs cannot determine *why* individual tasks were offloaded instead of running on existing POS hardware.

### 1.2 The Kolmogorov-Arnold Representation Theorem
To solve both problems simultaneously, KAN-Edge uses a **Kolmogorov-Arnold Network (KAN)** as its dynamic gating layer. Based on the Kolmogorov-Arnold representation theorem, any multivariate continuous function $f(\mathbf{x})$ on a bounded domain can be represented as a finite composition of continuous univariate functions and addition:

$$f(\mathbf{x}) = f(x_1, x_2, \dots, x_n) = \sum_{q=1}^{2n+1} \Phi_q \left( \sum_{p=1}^n \phi_{q,p}(x_p) \right)$$

Where:
* $n$ is the dimension of the input feature space ($n=5$ for KAN-Edge).
* $\phi_{q,p}: [0, 1] \to \mathbb{R}$ are learnable 1D functions placed on network edges (rather than fixed activation functions on nodes).
* $\Phi_q: \mathbb{R} \to \mathbb{R}$ are learnable outer transformation functions.

```
+---------------------------------------------------------------------------------------------+
|                          MLP vs. KAN ARCHITECTURAL COMPARISON                               |
+---------------------------------------------------------------------------------------------+
| PARAMETER             | MULTI-LAYER PERCEPTRON (MLP)       | KOLMOGOROV-ARNOLD NETWORK (KAN)|
+-----------------------+------------------------------------+--------------------------------+
| Activation Placement  | Fixed on nodes (ReLU, GELU, Sigmoid)| Learnable B-splines on edges   |
| Weight Type           | Linear scalar weight matrices ($W$) | Parameterized spline curves    |
| Parameter Efficiency  | High parameter count for non-linear| Very low parameter count       |
| Interpretability      | Zero (Black-box weight matrices)   | 100% (Exact symbolic formulas) |
| Mathematical Audit    | Impossible                         | Direct closed-form algebra     |
| Continuous Adaptation | Catastrophic forgetting risk       | Localized B-spline updates     |
+---------------------------------------------------------------------------------------------+
```

---

## 2. Feature Engineering & State Vector

The KAN routing gate evaluates an input vector $\mathbf{x} = [x_1, x_2, x_3, x_4, x_5]^T \in [0.0, 1.0]^5$ sampled at the exact millisecond an analytics request arrives.

### 2.1 Vector Definitions & Normalization Formulas

```
+-----------------------------------------------------------------------------------------------------+
| FEATURE  | SYMBOL    | RAW METRIC                   | NORMALIZATION FORMULA                         |
+----------+-----------+------------------------------+-----------------------------------------------+
| x1       | V_avail   | Free Shared APU VRAM (MB)    | x1 = clamp(VRAM_free_mb / VRAM_total_mb, 0, 1)|
| x2       | Q_len     | Active POS Billing Pressure  | x2 = clamp((ActiveTx + 0.5*ScanRate) / 10, 0, 1) |
| x3       | S_payload | Input Tensor / Payload (MB)  | x3 = clamp(Payload_mb / 50.0, 0, 1)          |
| x4       | L_bound   | Target Latency SLA (ms)      | x4 = 1.0 - clamp(LatencyBound_ms / 1000, 0, 1)|
| x5       | T_thermal | APU Thermal Headroom (deg C) | x5 = clamp((85.0 - DieTemp_C) / (85-40), 0, 1)|
+-----------------------------------------------------------------------------------------------------+
```

* **$x_1$ (Available VRAM):** Direct measurement of free unified memory available to the iGPU without triggering system paging.
* **$x_2$ (POS Pressure):** The mission-critical index. Combines current open transaction receipts with the 5-second rolling barcode scanner pulse rate.
* **$x_3$ (Payload Complexity):** Size of the frame batch or sensor array tensor.
* **$x_4$ (SLA Strictness):** Higher value means tighter latency requirements (e.g., $100\text{ms}$ SLA $\to x_4 = 0.90$; $800\text{ms}$ SLA $\to x_4 = 0.20$).
* **$x_5$ (Thermal Headroom):** AMD APUs downclock drastically above 82°C. $x_5$ penalizes local execution if the chassis is hot.

---

## 3. Network Architecture & Implementation (`pykan`)

### 3.1 Spline Representation
Each edge function $\phi(x)$ is parameterized as a linear combination of a smooth basis function $b(x) = \text{SiLU}(x) = \frac{x}{1 + e^{-x}}$ and a linear combination of cubic B-splines:

$$\phi(x) = w_b b(x) + w_s \sum_{i=0}^{G+k-1} c_i B_i(x)$$

Where:
* $G = 5$ (Grid intervals across $[0, 1]$).
* $k = 3$ (Cubic B-splines).
* $c_i$ are learnable control coefficients.

### 3.2 Network Topology
* **Layer Dimensions:** `[5, 3, 1]` (5 inputs $\to$ 3 hidden KAN nodes $\to$ 1 output scalar score).
* **Total Parameters:** Only $\approx 120$ trainable spline parameters (computable in $< 3.5\text{ms}$ on an edge CPU).

### 3.3 Training & Regularization Pipeline
The network is trained on synthetic and historical store traces using a multi-objective loss function:

$$\mathcal{L} = \mathcal{L}_{\text{task}} + \lambda_1 \mathcal{L}_{\text{billing\_penalty}} + \lambda_2 |\Phi|_1 + \lambda_3 \mathcal{S}_{\text{entropy}}$$

Where:
* $\mathcal{L}_{\text{task}}$: Accuracy of latency & execution success prediction.
* $\mathcal{L}_{\text{billing\_penalty}}$: Exponential loss penalty whenever a local execution coincides with a POS scan delay $> 5\text{ms}$ (enforcing "Billing Always Wins").
* $|\Phi|_1$: L1 sparsity regularization on spline coefficients to drive unneeded paths to zero for clean symbolic pruning.
* $\mathcal{S}_{\text{entropy}}$: Encourages dominant, interpretable pathways.

```python
# scripts/train_kan_gate.py snippet
import torch
from kan import KAN

# Initialize 5-input, 3-hidden, 1-output KAN
model = KAN(width=[5, 3, 1], grid=5, k=3, seed=42)

# Train with sparsity regularization to enable closed-form extraction
model.train(
    dataset, 
    opt="LBFGS", 
    steps=40, 
    lamb=0.01, 
    lamb_entropy=2.0
)

# Prune non-contributing spline edges
model.prune()

# Extract human-readable symbolic formula
formula = model.symbolic_formula(floating_digit=3)[0][0]
print(f"Extracted KAN Formula: {formula}")
```

---

## 4. Symbolic Extraction & Mathematical Auditability

### 4.1 The Symbolic Audit Engine
Once trained, the continuous B-splines are approximated via symbolic regression into standard elementary functions (linear combinations, polynomials, rational functions).

At runtime, for every single task evaluation, the KAN Gate logs:
1. The exact continuous evaluation score $\in [-10.0, +10.0]$.
2. The evaluated algebraic formula with instantiated input coefficients.
3. The routing destination (`LOCAL_IGPU` or `CLOUD_GPU`).

### 4.2 Representative Operating Regimes & Sample Equations

#### Regime 1: Calm Store Hours (Local iGPU Processing)
* **Conditions:** Cash register idle, APU cool, VRAM plentiful ($x_1=0.88, x_2=0.00, x_3=0.15, x_4=0.50, x_5=0.80$).
* **Instantiated Symbolic Formula:**
  $$\text{Score} = 0.852 \cdot x_1 - 1.240 \cdot x_2 - 0.412 \cdot x_3 + 0.285 \cdot x_4 + 0.190 \cdot x_5$$
  $$\text{Score} = 0.852(0.88) - 0 - 0.412(0.15) + 0.285(0.50) + 0.190(0.80) = \mathbf{+0.982}$$
* **Decision:** $\mathbf{+0.982 \ge 0.50 \implies \text{LOCAL\_IGPU}}$
* **Audit Trail Justification:** Zero cloud cost incurred. Local execution justified by 88% free VRAM and zero checkout contention.

#### Regime 2: Peak Checkout Wave (Cloud Fallback)
* **Conditions:** Friday evening grocery rush; cashier scanning rapidly ($x_1=0.45, x_2=0.80, x_3=0.30, x_4=0.70, x_5=0.50$).
* **Instantiated Symbolic Formula:**
  $$\text{Score} = 0.852(0.45) - 1.240(0.80) - 0.412(0.30) + 0.285(0.70) + 0.190(0.50) = \mathbf{-0.435}$$
* **Decision:** $\mathbf{-0.435 < 0.50 \implies \text{CLOUD\_GPU}}$
* **Audit Trail Justification:** Cloud cost of \$0.00045 incurred. Local execution denied due to heavy negative checkout pressure ($-0.992$ penalty on $x_2$), preserving billing software smoothness.

#### Regime 3: Heavy Payload / Multi-Camera Re-ID
* **Conditions:** Register idle, but incoming payload is a 45 MB multi-camera tensor ($x_1=0.70, x_2=0.00, x_3=0.95, x_4=0.90, x_5=0.75$).
* **Instantiated Symbolic Formula:**
  $$\text{Score} = 0.852(0.70) - 0 - 0.412(0.95) + 0.285(0.90) + 0.190(0.75) = \mathbf{+0.428}$$
* **Decision:** $\mathbf{+0.428 < 0.50 \implies \text{CLOUD\_GPU}}$
* **Audit Trail Justification:** Cloud cost incurred because payload size ($0.95$) drove score below the $0.50$ safety margin to prevent local iGPU starvation.

---

## 5. Audit Log Ledger & Schema

Every decision is permanently recorded in the edge SQLite store and synced to PostgreSQL:

```json
{
  "audit_event_id": "aud-8891-4412-bce7",
  "timestamp_utc": "2026-11-09T14:30:15.122Z",
  "store_id": "ST-0991",
  "terminal_id": "POS-REG-03",
  "task_type": "footfall_estimation",
  "routing_decision": "LOCAL_IGPU",
  "kan_evaluation": {
    "score": 0.841,
    "threshold": 0.500,
    "symbolic_formula": "score(0.841) = 0.852*V(0.80) - 1.240*Q(0.00) - 0.412*S(0.20) + 0.285*L(0.50) + 0.190*T(0.72)",
    "primary_factor": "HIGH_AVAILABLE_VRAM",
    "preemption_engaged": false
  },
  "metrics_snapshot": {
    "vram_free_mb": 3280,
    "active_checkout_tx": 0,
    "barcode_scans_per_sec": 0.0,
    "payload_mb": 10.2,
    "die_temp_celsius": 52.5
  },
  "financial_impact": {
    "cloud_cost_incurred_usd": 0.0000,
    "cloud_cost_saved_usd": 0.00045
  }
}
```

---

## 6. Financial Reconciliation & Executive Reporting

### 6.1 The "Why Did We Pay AWS?" Report
Retail CFOs and Operations Directors receive an automated monthly reconciliation report generated directly from the KAN symbolic ledger:

```
+---------------------------------------------------------------------------------------+
|                    STORE #0991 CLOUD BILLING RECONCILIATION REPORT                    |
|                        Period: October 1, 2026 - October 31, 2026                     |
+---------------------------------------------------------------------------------------+
| Total Analytics Inferences:       1,450,000 tasks                                     |
| Local Edge Inferences (iGPU):     1,087,500 tasks (75.0% - $0.00 spend)               |
| Cloud Offload Inferences:           362,500 tasks (25.0% - $163.12 AWS GPU spend)     |
+---------------------------------------------------------------------------------------+
| MATHEMATICAL OFF-LOAD JUSTIFICATION BREAKDOWN (KAN SYMBOLIC AUDIT):                   |
| 1. High Checkout Activity Spike (Q_len factor >= 0.60):         62.4% ($101.78)       |
|    -> Preserved 0ms billing lag across 18,200 peak customer transactions              |
| 2. Oversized Payload Exceeding VRAM Safe Threshold (S_payload):  28.1% ($45.83)        |
|    -> Prevented local APU memory exhaustion & crash                                   |
| 3. High Die Temperature / Thermal Protection (T_thermal):        9.5% ($15.51)        |
|    -> Protected POS hardware lifespan during air-conditioning failure                 |
+---------------------------------------------------------------------------------------+
| NET SAVINGS REALIZED VS FULL CLOUD DEPLOYMENT:                  $489.38 / terminal/mo |
+---------------------------------------------------------------------------------------+
```

