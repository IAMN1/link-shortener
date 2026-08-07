

def test_request_logging(client, test_logger):
    """Request should be logged with start and completion messages."""


    response = client.get("/health")

    assert response.status_code == 200
    # Check that test_logger.messages has the expected entries
    started = any(msg[1] == "Request started" for msg in test_logger.messages)
    completed = any(msg[1] == "Request completed" for msg in test_logger.messages)
    assert started, "Message 'Request started' not found"
    assert completed, "Message 'Request completed' not found"