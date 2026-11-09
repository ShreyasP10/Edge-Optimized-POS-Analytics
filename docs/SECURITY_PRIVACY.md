# Security, Privacy & Compliance Architecture
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Compliance Scope:** PCI-DSS v4.0, GDPR (Article 25 & 32), CCPA / CPRA  

---

## 1. Security Philosophy: Zero Trust at the Checkout Counter

Deploying edge artificial intelligence directly on retail Point-of-Sale (POS) terminals requires extreme security rigor. Because checkout terminals handle payment card processing and customer transactions, any co-located software must guarantee zero operational risk, zero data leakage, and complete compliance isolation.

KAN-Edge is engineered around three non-negotiable security axioms:
1. **Absolute PCI-DSS Scope Demarcation:** The analytics platform has zero ingress, zero memory access, and zero network visibility into the Cardholder Data Environment (CDE).
2. **Zero Raw Video Egress (Data Minimization):** Customer video feeds and raw biometric pixels never leave volatile memory on the edge device and are never written to disk or transmitted across the WAN.
3. **Outbound-Only Air-Gapped Network Posture:** The edge terminal never opens inbound public internet ports. All cloud offloading and telemetry sync is initiated strictly via outbound, mutually authenticated TLS 1.3 connections.

---

## 2. PCI-DSS v4.0 Scoping & Separation Analysis

Under PCI-DSS v4.0, any software or process co-located on a system component that stores, processes, or transmits cardholder data (CHD) or sensitive authentication data (SAD) could inadvertently pull that entire component into compliance audit scope.

```
+----------------------------------------------------------------------------------------------------+
|                                    POS HARDWARE HOST APU                                           |
|                                                                                                    |
|  +--------------------------------------------------+   +---------------------------------------+  |
|  |             CDE TRUSTED ZONE (PCI SCOPE)         |   |      NON-CDE ZONE (KAN-EDGE SYSTEM)   |  |
|  |                                                  |   |                                       |  |
|  | - Cardholder Processing Application              |   | - K3s Analytics Pod / FastAPI         |  |
|  | - EMV Chip / Magnetic Stripe Reader              |   | - KAN Gating Engine (pykan)           |  |
|  | - Hardware PIN Pad & Encrypted Keypad (PED)     |   | - ONNX Runtime (DirectML / Vulkan)    |  |
|  | - Virtual Memory: Locked & Scrambled            |   | - SQLite Local Feature Store          |  |
|  | - Network: VLAN 10 (Bank Acquirer Gateway Only)  |   | - Network: VLAN 30 / Localhost Socket |  |
|  +--------------------------------------------------+   +---------------------------------------+  |
|                           ^                                                 |                      |
|                           |=================================================|                      |
|                                         AIR-GAP DEMARCATION                                        |
|                             - Zero IPC / Shared Memory between Zones                               |
|                             - No common file system mounts                                         |
|                             - Analytics runs under restricted UID (UID 10001)                      |
+----------------------------------------------------------------------------------------------------+
```

### 2.1 Technical Controls Enforcing PCI Demarcation
* **Kernel Namespace & cgroup Isolation:** The KAN analytics engine runs inside an unprivileged container namespace with `CAP_DROP=ALL`, preventing kernel module inspection, raw socket binding, or host device manipulation.
* **Device Blacklisting:** The container runtime explicitly forbids access to USB major/minor nodes corresponding to serial card readers, chip-and-pin pads, and encrypted keyboard controllers (`/dev/ttyUSB*`, `/dev/input/by-id/usb-POS-PED*`).
* **Memory Paging Protections:** The POS billing software utilizes OS memory locking (`mlock` on Linux, `VirtualLock` on Windows) to prevent sensitive transaction structures from being paged to shared swap space.

---

## 3. Privacy by Design: Zero Raw Video Egress

In compliance with the **EU General Data Protection Regulation (GDPR Article 5: Data Minimization)** and the **California Consumer Privacy Act (CCPA/CPRA)**, KAN-Edge enforces an in-memory feature extraction model.

```
[Store Camera] ---> (Raw Video Frame) 
                          |
                          v
         +----------------------------------+
         |      VOLATILE RAM BUFFER         |
         |      - Never written to disk     |
         |      - Shared memory (/dev/shm)  |
         +----------------------------------+
                          |
                          v
         +----------------------------------+
         |     QUANTIZED ONNX RUNTIME       |
         |     - INT8 Person Detection      |
         +----------------------------------+
                          |
         +----------------+----------------+
         |                                 |
         v                                 v
[Extracted Coordinates]          [RAW FRAME PURGED]
- Footfall: +1                   - memset_s(buffer, 0, size)
- Bounding Box: [120, 80, ...]   - RAM immediately reclaimed
- Dwell time: 4.2s               - Zero residual imagery
         |
         v
[SQLite / Postgres Sync] (JSON Only)
```

### 3.1 What is Stored & Synced vs. What is Destroyed
* **Destroyed Instantly Post-Inference:**
  * Raw JPEG/PNG image frames.
  * RTSP/H.264 video streams.
  * High-resolution customer facial crops.
* **Retained Locally (SQLite):**
  * Anonymized integer counts (e.g., `footfall_count: 3`).
  * Bounding box geometry without texture data (`[x1, y1, x2, y2]`).
  * Time-stamped dwell-time durations in seconds.
* **Synced to Cloud (PostgreSQL):**
  * Spatio-temporal aggregates per store aisle (e.g., `Aisle_4_dwell_avg_15m: 38s`).
  * KAN symbolic routing justifications and hardware telemetry snapshots.

---

## 4. Network Security & Cryptographic Handshake

### 4.1 Zero Inbound Ports Policy
The edge terminal accepts connections **strictly from the local loopback interface (`127.0.0.1`)**. No public or WAN-accessible listening ports exist on the POS device.

### 4.2 Outbound Mutual TLS (mTLS)
When offloading tasks to the cloud or synchronizing SQLite feature batches to PostgreSQL:
* **Protocol:** TLS 1.3 only (cipher suites: `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`).
* **Authentication:** Hardware-bound X.509 client certificate stored inside the POS terminal's Trusted Platform Module (TPM 2.0).
* **Certificate Pinning:** The edge client hardcodes and pins the cloud gateway's intermediate Certificate Authority (CA) public key to prevent DNS spoofing and Man-in-the-Middle (MitM) attacks.

---

## 5. Threat Modeling (STRIDE Analysis)

| Threat Category | Potential Threat Vector | Mitigating Architectural Control | Residual Risk Level |
| :--- | :--- | :--- | :--- |
| **Spoofing** | Attacker impersonates a POS edge terminal to flood cloud GPU resources. | Cloud API Gateway validates unique hardware-backed client certificate (TPM 2.0) and terminal UUID on every request. | **Low** |
| **Tampering** | Malicious background pod alters POS billing receipts or item pricing. | Strict OS cgroups & namespace isolation. Zero shared memory or socket connection between POS billing and analytics. | **Negligible** |
| **Repudiation** | Franchisee denies cloud GPU consumption on monthly bill. | KAN Gate cryptographically signs the symbolic formula string and hardware state snapshot in the append-only audit ledger. | **Low** |
| **Information Disclosure**| Eavesdropper captures surveillance video frames over store Wi-Fi. | Video never traverses Wi-Fi/WAN. Camera connects via physical PoE or localhost; raw frames zeroed in RAM immediately. | **Negligible** |
| **Denial of Service** | Analytics workload starves POS billing app during peak customer rush. | **Billing Always Wins:** cgroup priority pinning, low I/O priority, real-time telemetry preemption under $< 5\text{ms}$. | **Low** |
| **Elevation of Privilege**| Compromised analytics pod attempts to gain host root privileges. | Container runs as non-root (`UID 10001`), root filesystem mounted read-only (`read_only_rootfs: true`), `no-new-privileges` enforced. | **Negligible** |

---

## 6. Cryptographic Audit Trail & Forensic Integrity

To guarantee that the mathematical formulas generated by the KAN gate cannot be tampered with or retroactively altered:
1. **Hash Chaining:** Each record in the local SQLite audit ledger contains a SHA-256 hash incorporating the previous record's hash:
   $$H_k = \text{SHA256}(H_{k-1} \parallel \text{Timestamp} \parallel \text{TaskID} \parallel \text{KAN\_Formula} \parallel \text{RoutingDecision})$$
2. **Periodic Checkpoint Signing:** Every 60 minutes, the cumulative ledger hash is signed with the node's private key and pushed to the cloud PostgreSQL database.
3. **Forensic Reconciliation:** In the event of a billing dispute between the retailer and cloud provider, an automated verification script recalculates the hash chain across both edge SQLite and cloud PostgreSQL records to prove tamper-free authenticity.

