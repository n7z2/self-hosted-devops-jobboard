.PHONY: build run stop logs scrape clean help

# Default target
help:
	@echo "DevOps Job Board - Available commands:"
	@echo ""
	@echo "  make build    - Build the Docker container"
	@echo "  make run      - Start the job board (http://localhost:5000)"
	@echo "  make stop     - Stop the job board"
	@echo "  make logs     - View container logs"
	@echo "  make clean    - Remove container and image"
	@echo ""

# Build the Docker image
build:
	docker build -t jobboard .

# Run the container
run:
	@mkdir -p data
	docker run -d --name jobboard \
		-p 5000:5000 \
		-v $(PWD)/data:/app/data \
		jobboard
	@echo ""
	@echo "Job Board running at: http://localhost:5000"
	@echo ""

# Stop the container
stop:
	docker stop jobboard 2>/dev/null || true
	docker rm jobboard 2>/dev/null || true

# View logs
logs:
	docker logs -f jobboard

# Clean up
clean: stop
	docker rmi jobboard 2>/dev/null || true

# Rebuild and run
restart: stop build run
