#analysis part 
 #what is happening here is that read_logs() -> gives sample process data
 #main() -> prints it
def read_logs():
    print("Reading logs...")
    return [("P1", "P2"), ("P2", "P3"), ("P3", "P1")]

# def main():
#     data = read_logs()
#     print("Logs:", data)

# if __name__ == "__main__":
#     main()
def build_graph(logs): #takes input like [("P1", "P2"), ("P2", "P3"), ("P3", "P1")]
    graph={} # we are creating empty graph over here
    for a, b in logs: #looping through logs
        if a not in graph:
            graph[a] = []
        graph[a].append(b)
    return graph

#Deadlock work 
def detect_deadlock(graph):
    visited = set()
    stack = []

    def dfs(node):
        if node in stack:
            cycle_index = stack.index(node)
            return stack[cycle_index:] + [node]
        
        if node in visited:
            return None
        
        visited.add(node)
        stack.append(node)

        for neighbor in graph.get(node, []):
            cycle = dfs(neighbor)
            if cycle:
                return cycle
        
        stack.pop()
        return None

    for node in graph:
        cycle = dfs(node)
        if cycle:
            return cycle

    return None
    #Main function 
def main():
    logs = read_logs()
    graph = build_graph(logs)

    print("Graph:", graph)

    cycle = detect_deadlock(graph)

    if cycle:
        print("Deadlock detected 💀")
        print("Cycle:", " → ".join(cycle))
    else:
        print("No deadlock ✅")
# Run program
if __name__ == "__main__":
    main()