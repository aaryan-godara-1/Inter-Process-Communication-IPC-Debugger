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
    visited = set() #stores node we already visited, avoids repeating work
    stack = set() #tracks current path

    def dfs(node):
        if node in stack:
            return True
        
        if node in visited:
            return False
        
        visited.add(node)
        stack.add(node)

        for neighbor in graph.get(node, []):
            if dfs(neighbor):
                return True
        
        stack.remove(node)
        return False

    for node in graph:
        if dfs(node):
            return True

    return False

    #Main function 
def main():
    logs = read_logs()
    graph = build_graph(logs)

    print("Graph:", graph)

    if detect_deadlock(graph):
        print("Deadlock detected 💀")
    else:
        print("No deadlock ✅")


# Run program
if __name__ == "__main__":
    main()