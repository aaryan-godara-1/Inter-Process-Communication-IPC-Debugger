#analysis part 
 #what is happening here is that read_logs() -> gives sample process data
 #main() -> prints it
def read_logs():
    print("Reading logs...")
    return [("P1", "P2"), ("P2", "P3"), ("P3", "P1")]

def main():
    data = read_logs()
    print("Logs:", data)

if __name__ == "__main__":
    main()
def build_graph(logs): #takes input like [("P1", "P2"), ("P2", "P3"), ("P3", "P1")]
    graph={} # we are creating empty graph over here
    for a, b in logs: #looping through logs
        if a not in graph:
            graph[a] = []
        graph[a].append(b)
    return graph