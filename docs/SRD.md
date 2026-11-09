# System Requirements Document (SRD)
## Project: KAN-Edge POS Analytics (Edge-Optimized POS Analytics)
**Document Version:** 1.0.0  
**Standard:** ISO/IEC/IEEE 15288:2015 Systems Engineering  
**Scope:** Complete Edge-to-Cloud System Hardware & Platform Specification  

---

## 1. System Scope & Hardware Architecture

The KAN-Edge POS Analytics system integrates edge computer vision, interpretability networks, and cloud elasticity into commercial Point-of-Sale (POS) terminal hardware.

```
+----------------------------------------------------------------------------------------------------+
|                                  PHYSICAL POS SYSTEM ARCHITECTURE                                  |
|                                                                                                    |
|  +----------------------------------------------------------------------------------------------+  |
|  |                             PRIMARY APU / SYSTEM-ON-CHIP (SOC)                               |  |
|  |  - x86-64 Architecture (AMD Ryzen Embedded V1000/V2000/R1000 or Intel Tiger/Alder Lake Core)|  |
|  |  - Integrated GPU (AMD Radeon Vega 3-11 / RDNA 2, Intel Iris Xe)                             |  |
|  |  - Unified Memory Controller (Dual-Channel DDR4-2400 to DDR5-4800)                          |  |
|  +----------------------------------------------------------------------------------------------+  |
|                    |                                             |                                 |
|                    v                                             v                                 |
|  +------------------------------------+        +------------------------------------------------+  |
|  |       DISPLAYS & PERIPHERALS       |        |          STORAGE & NETWORK BUS                 |  |
|  |  - Cashier Touch Display (eDP/LVDS)|        |  - NVMe PCIe M.2 SSD / SATA-III SSD            |  |
|  |  - Customer Facing Display (HDMI)  |        |  - Intel/Realtek Gigabit Ethernet (802.3ab)    |  |
|  |  - Barcode Scanner (USB HID/Serial)|        |  - Dual-Band Wi-Fi 5/6 (802.11ac/ax)           |  |
|  |  - Card Reader / PIN Pad (PCI CDE) |        |  - Hardware Security: TPM 2.0 Cryptoprocessor  |  |
|  +------------------------------------+        +------------------------------------------------+  |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Hardware Interface Requirements

### 2.1 Compute & Processing Unit (SRD-HW-01)
* **Processor Family:** x86-64 multi-core processor (minimum 4 physical cores, 8 execution threads).
* **Clock Speeds:** Base clock $\ge 2.0\text{ GHz}$, Turbo boost $\ge 3.2\text{ GHz}$.
* **Thermal Design Power (TDP):** Configurable TDP ($12\text{W}\text{--}35\text{W}$) to support fanless sealed retail chassis.
* **Integrated GPU (iGPU):**
  * Hardware acceleration engine supporting DirectX 12 Feature Level 12_0 (Windows) and Vulkan 1.2+ (Linux).
  * Minimum 192 stream processors / 3 Compute Units (AMD) or 48 Execution Units (Intel).
  * Rapid Packed Math (FP16 compute rate at least double FP32 throughput).

### 2.2 System Memory & Bandwidth (SRD-HW-02)
* **Capacity:** Minimum 8 GB DDR4/DDR5 unified RAM; recommended 16 GB for high-traffic supermarkets.
* **Channel Architecture:** **Dual-channel configuration is mandatory.** Minimum theoretical bandwidth of $38.4\text{ GB/s}$ (DDR4-2400 dual-channel) or $51.2\text{ GB/s}$ (DDR4-3200 dual-channel).
* **VRAM Aperture Reservation:**
  * Minimum UMA allocation: 1024 MB configured in UEFI/BIOS.
  * Maximum dynamic GTT shared allocation: Clamped to 50% of free system RAM.

### 2.3 Storage Subsystem (SRD-HW-03)
* **Bus Interface:** PCIe Gen 3x2 / 3x4 NVMe M.2 SSD or SATA 6Gbps SSD.
* **Capacity:** Minimum 64 GB dedicated partition for edge OS, model weights, and SQLite buffer.
* **Endurance & Write Cycles:** Minimum 150 TBW (Terabytes Written) to support continuous SQLite WAL ring buffering over a 5-year hardware lifecycle.

### 2.4 Peripheral & Point-of-Sale Bus Interfaces (SRD-HW-04)
* **USB Interfaces:** Minimum 4x USB 3.2 Gen 1 ports for high-speed camera ingest or external frame grabbers; 2x USB 2.0 for keyboard/mouse.
* **Scanner / Serial:** RS-232 COM port or USB HID with Virtual COM Port (VCP) driver support.
* **Camera Ingestion:** USB 3.0 UVC (Universal Video Class) camera interface or Gigabit PoE RTSP IP camera feed over secondary NIC.

---

## 3. Platform & Operating System Requirements

### 3.1 Operating System Environments (SRD-OS-01)
* **Windows Tier:** Windows 10 IoT Enterprise LTSC 2021 or Windows 11 IoT Enterprise (64-bit).
  * Required Components: Windows Subsystem for Linux (WSL2) OR native Win32 container execution engine, DirectML runtime runtime libraries (`directx-directml`).
* **Linux Tier:** Ubuntu 22.04 LTS Point-of-Service / SUSE Linux Enterprise Point of Service (SLEPOS 15).
  * Kernel Version: Linux Kernel $\ge 5.15$ with `cgroup2` hierarchy mounted and `amdgpu` driver compiled.

### 3.2 Process Isolation & Scheduling Requirements (SRD-OS-02)
* **Resource Partitioning:**
  * CPU Cores 0 and 1 must be quarantined for POS billing and OS kernel handling.
  * CPU Cores 2 and 3 allocated to K3s / analytics container with a maximum quota of $50\%$.
* **Scheduling Priority:**
  * POS Billing Software: Pinned to `SCHED_FIFO` / `nice -20` (Linux) or `HIGH_PRIORITY_CLASS` (Windows).
  * Analytics Engine: Bound to `SCHED_IDLE` / `nice 19` (Linux) or `IDLE_PRIORITY_CLASS` (Windows).
* **Memory Out-of-Memory Protection:**
  * Host Billing process: `oom_score_adj = -1000`.
  * Analytics worker pod: `oom_score_adj = +800`.

---

## 4. Network & Communications Requirements

### 4.1 Local Edge Connectivity (SRD-NET-01)
* **Ethernet Adapter:** 10/100/1000 Base-T Gigabit Ethernet (RJ-45) with Wake-on-LAN (WoL) support.
* **Local Latency:** Local IPC between camera ingestion and FastAPI gateway must complete in $\le 2\text{ ms}$.

### 4.2 WAN & Cloud Elasticity Requirements (SRD-NET-02)
* **Broadband Egress:** Minimum 5 Mbps upload bandwidth for fallback bursts; 500 Kbps for idle telemetry sync.
* **Protocol & Encryption:** TLS 1.3 encrypted gRPC / HTTPS over TCP port 443.
* **Offline Toleration:** The terminal must support continuous offline local operation for up to 168 consecutive hours (7 days) without loss of telemetry or footfall data.

---

## 5. Environmental & Reliability Constraints

### 5.1 Physical Environment (SRD-ENV-01)
* **Operating Temperature:** $0^\circ\text{C}$ to $40^\circ\text{C}$ ($32^\circ\text{F}$ to $104^\circ\text{F}$) ambient.
* **Relative Humidity:** 10% to 90% non-condensing.
* **Ingress Protection:** Minimum IP54 splash resistance on cashier touch panels.
* **Cooling:** Passive convection heatsink or low-RPM acoustic fan ($\le 28\text{ dBA}$ at 1 meter).

### 5.2 Reliability & Mean Time Between Failures (SRD-ENV-02)
* **Target Hardware MTBF:** $> 50,000$ operating hours ($> 5.7\text{ years}$ continuous $24/7/365$ operation).
* **Reboot Recovery:** Upon unexpected AC power loss, the edge analytics service must recover automatically into its previous state within 45 seconds of OS boot.

