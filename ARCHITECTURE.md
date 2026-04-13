# IPC Debugger: Kernel-Level Architecture

## System Overview

The IPC Debugger is a **kernel-level instrumentation and visualization system** that captures real system IPC events and presents them in a minimal graph-based UI.

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│              Kernel Event Capture Layer                      │
│  (eBPF/kprobes on Linux, ETW on Windows, DTrace on macOS)   │
└─────────────────────┬───────────────────────────────────────┘
                      │ Raw kernel events
                      ▼
┌─────────────────────────────────────────────────────────────┐
│         Event Normalization & Filtering Layer                │
│  • Timestamp alignment                                        │
│  • Process/thread context enrichment                          │
│  • Selective filtering & sampling                             │
└─────────────────────┬───────────────────────────────────────┘
                      │ Normalized IPC events
                      ▼
┌─────────────────────────────────────────────────────────────┐
│           Event Timeline Engine (In-Memory DB)               │
│  • Chronological stream of events                             │
│  • Ring buffer for overflow handling                          │
│  • Causal relationships tracking                              │
└─────────────────────┬───────────────────────────────────────┘
                      │ Time-indexed events
                      ▼
┌─────────────────────────────────────────────────────────────┐
│            Analysis & Correlation Engine                     │
│  • Request-response flow stitching                            │
│  • Lock ownership tracking                                    │
│  • Wait chain reconstruction                                  │
│  • Deadlock detection                                         │
└─────────────────────┬───────────────────────────────────────┘
                      │ Enriched event chains
                      ▼
┌─────────────────────────────────────────────────────────────┐
│           Debugging & Observation Layer                      │
│  • Breakpoints & watchpoints                                  │
│  • Anomaly detection & alerting                               │
│  • Record & replay engine                                     │
└─────────────────────┬───────────────────────────────────────┘
                      │ Correlated flows + alerts
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Web & REST API Layer                            │
│  • Real-time WebSocket updates                                │
│  • RESTful query interface                                    │
│  • Export and integration endpoints                           │
└─────────────────────┬───────────────────────────────────────┘
                      │ JSON/binary data
                      ▼
┌─────────────────────────────────────────────────────────────┐
│          Minimal Graph-Based UI (Browser)                    │
│  • Ring layout with processes                                │
│  • Central resource nodes                                    │
│  • Dynamic edge visualization                                │
│  • Real-time state updates                                    │
└─────────────────────────────────────────────────────────────┘
```

## Core Event Model

### IPC Event Structure

```typescript
interface IPCEvent {
  // Metadata
  event_id: string;              // Unique event ID
  timestamp: number;             // ns since kernel start
  correlation_id: string;        // Links related events across processes
  
  // Context
  process_id: number;
  thread_id: number;
  parent_process_id?: number;
  
  // IPC Details
  ipc_type: IPCType;            // pipe, socket, shared_mem, mutex, etc.
  resource_id: string;          // Handle to the resource
  event_type: EventType;        // SEND, RECV, ACQUIRE, RELEASE, etc.
  
  // Payload
  payload_size: number;         // Bytes transferred
  payload_hash?: string;        // SHA256 for correlation
  payload_preview?: string;    // First N bytes (base64 or masked)
  payload_masked: boolean;      // Whether sensitive data was masked
  
  // Timing
  latency_ns?: number;          // Wait time if applicable
  cpu_cycles?: number;          // CPU cost
  
  // Status
  result: EventResult;          // SUCCESS, BLOCKED, ERROR
  error_code?: number;
  
  // Flags
  is_blocking: boolean;
  is_retry: number;             // 0 for first attempt, >0 for retries
  
  // Source tracking
  source: EventSource;          // KERNEL, USERSPACE_HOOK, INFERRED
  confidence: number;           // 0-100%
}

type IPCType = 
  | 'pipe' | 'named_pipe'
  | 'unix_socket' | 'tcp_socket' | 'udp_socket'
  | 'shared_memory'
  | 'mutex' | 'semaphore' | 'rwlock' | 'futex'
  | 'message_queue'
  | 'file_descriptor'
  | 'signal'
  | 'epoll' | 'uring';

type EventType =
  | 'SEND' | 'RECV' | 'REQUEST' | 'RESPONSE'
  | 'ACQUIRE' | 'RELEASE' | 'WAIT' | 'SIGNAL'
  | 'ENQUEUE' | 'DEQUEUE'
  | 'ATTACH' | 'DETACH'
  | 'CREATE' | 'DESTROY'
  | 'MAP' | 'UNMAP';

type EventResult = 'SUCCESS' | 'BLOCKED' | 'TIMEOUT' | 'ERROR' | 'QUEUED';
type EventSource = 'KERNEL' | 'USERSPACE_HOOK' | 'INFERRED';
```

### Causal Chain Model

```typescript
interface CausalChain {
  chain_id: string;
  start_event_id: string;
  end_event_id: string;
  
  events: IPCEvent[];           // Ordered events in chain
  process_path: number[];       // Process IDs traversed
  
  // Timing
  total_latency_ns: number;
  hop_count: number;
  
  // Classification
  chain_type: ChainType;         // request-response, producer-consumer, lock-wait, signal-wait
  is_complete: boolean;          // Whether chain has ended
  completion_time_ns?: number;
}

type ChainType = 'request-response' | 'producer-consumer' | 'lock-wait' | 'signal-wait' | 'barrier-sync';
```

### Lock & Wait Graph

```typescript
interface LockEvent {
  lock_id: string;
  owner_pid: number;
  owner_tid: number;
  acquire_time_ns: number;
  release_time_ns?: number;
  
  waiters: WaitEntry[];
  lock_type: LockType;
  lock_value?: number;           // For semaphores
}

interface WaitEntry {
  waiter_pid: number;
  waiter_tid: number;
  wait_start_ns: number;
  wait_end_ns?: number;
  waited_ns: number;
  wait_reason: WaitReason;
  is_resoled: boolean;
}

type WaitReason = 'lock_contention' | 'queue_full' | 'resource_unavailable' | 'signal_wait';

interface DeadlockCycle {
  cycle_id: string;
  detected_at_ns: number;
  processes: number[];
  locks: string[];
  
  path: {
    pid: number;
    lock_id: string;
    waiting_for_pid: number;
  }[];
}
```

## Data Flow Pipeline

### 1. Kernel Event Capture (OS-Specific)

#### Linux - eBPF Approach
- **Tracepoints**: sys_read, sys_write, sys_futex, sys_sem*
- **kprobes**: mutex_lock, mutex_unlock, wake_up_q
- **Ring buffer**: Circular buffer for event streaming
- **Overhead**: < 5% CPU impact with selective sampling

#### Windows - ETW Approach
- **Providers**: Kernel Logger, ThreadPoolProvider
- **Events**: ReadyThread, ContextSwitch, DPC, ISR
- **Real-time consumers**: Direct kernel event streaming

#### macOS - DTrace Approach
- **Probes**: syscall:::enter/return, locks:::lock-acquire/release
- **Scripts**: Dynamic sampling of IPC primitives

### 2. Event Normalization

- Timestamp alignment across cores
- Convert OS-specific codes to unified event model
- Add process name/thread name context
- Mask sensitive payloads

### 3. Timeline Engine

- In-memory event stream (ring buffer)
- Configurable retention (rolling window)
- Indexed by (timestamp, process_id, resource_id)
- Supports forward and backward iteration

### 4. Causal Analysis

- **Request-Response Matching**:   - Match SEND → RECV by correlation_id
  - Match ACQUIRE → RELEASE for same lock
  - Match WAIT → SIGNAL events

- **Flow Stitching**:
  - Process A sends to queue → Process B receives from queue
  - Reconstruct multi-hop consumer chains
  - Label data flows as measured vs. inferred

- **Lock Graph**:
  - Track who owns what lock
  - Who waits for whom
  - Detect cycles (deadlocks)

### 5. Debugging Hooks

- **Breakpoints**: Pause when condition matches
  - Process pair (A → B)
  - Latency threshold exceeded
  - Lock held > X ms
  - Message queue depth exceeded

- **Watchpoints**: Log when accessed
  - Resource accessed by any process
  - Specific message type received

### 6. Record & Replay

- Stream events to disk file
- Snapshot process memory references (pointers)
- Replay: Step through events, inspect state at each point
- Deterministic: Same event ordering guaranteed

## Configuration & Control

### Selective Capture

```json
{
  "capture": {
    "ipc_types": ["pipe", "socket", "mutex"],
    "processes": [1234, 5678],
    "min_latency_ns": 1000000,
    "sample_rate": 0.1,
    "payload_capture": true,
    "payload_max_size": 256,
    "mask_sensitive": true
  }
}
```

### Alerting Rules

```json
{
  "alerts": [
    {
      "name": "high_latency",
      "condition": "event.latency_ns > 50000000",
      "action": "notify_ui"
    },
    {
      "name": "queue_buildup",
      "condition": "queue_depth > 1000",
      "action": "log_and_alert"
    },
    {
      "name": "deadlock_risk",
      "condition": "detect_hold_and_wait_pattern()",
      "action": "highlight_and_breakpoint"
    }
  ]
}
```

## UI Design Principles

### Graph Layout

- **Outer Ring**: Process nodes (24 slots per ring, multiple rings if needed)
- **Center**: System resources (pipes, sockets, shared memory, locks)
- **Edges**: IPC connections, color-coded by resource type
- **Stability**: Node positions never move after initial placement

### Node Colors & Edge Colors

- **Edges**:
  - Red: CPU/scheduling
  - Blue: Memory/shared memory
  - Orange: Disk/file operations
  - Green: Network/sockets
  - Purple: Locks/synchronization
  - Black: Messages/IPC

### Interaction Model

1. **Hover**: Show tooltips with event counts, latency
2. **Click Process**: Highlight all IPC flows involving that process
3. **Click Resource**: Show all processes interacting with it
4. **Right-click**: Context menu (breakpoint, zoom, export)

### Real-Time Updates

- WebSocket stream of new events
- Batch updates every 100ms
- Fade in new edges, pulse on activity
- Alert animations (red border flash)

## Performance & Overhead

### Target Metrics

- Kernel capture overhead: < 5%
- Event latency: < 1ms P99
- Ring buffer retention: 10-60 seconds of events
- Memory footprint: < 500MB for 1 hour trace

### Optimization Techniques

- Ring buffer with configurable size
- Event sampling (1%, 10%, 100%)
- Selective capture by process/resource
- Payload compression for storage
- Lazy deserialization

## Security Model

### Data Trust Levels

1. **Direct**: Captured directly from kernel
2. **Derived**: Computed from multiple events (e.g., latency)
3. **Inferred**: Guessed based on heuristics

### Access Control

- Role-based access (Admin, Operator, Viewer)
- Audit log for all debugger operations
- Payload masking for sensitive systems

## Integration Points

### Export Formats

1. **JSON**: Standard trace format
2. **OpenTelemetry**: For APM platforms
3. **Binary**: Efficient wire format for streaming
4. **Replay File**: Deterministic replay snapshots

### APIs

- gRPC service for remote collection
- REST API for querying
- WebSocket for real-time streams
- Library bindings for languages (Go, Rust, Python)
