# macOS client

This is an optional adapter boundary. It may collect status from local agent tools only if direct Agent/API-to-MQTT delivery proves less reliable or less usable.

Any adapter emits the versioned `AgentStatus` contract; it never owns device UI semantics.
