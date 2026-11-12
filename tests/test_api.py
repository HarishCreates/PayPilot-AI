from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_dashboard_summary_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DATA_FILE", tmp_path / "transactions.json")
    main.write_transactions([
        {"order_id": "TEST-1", "amount": 12.5, "currency": "USD", "status": "COMPLETED", "risk_flag": False},
        {"order_id": "TEST-2", "amount": 7, "currency": "USD", "status": "PENDING", "risk_flag": True},
    ])
    response = client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_sales"] == 12.5
    assert data["completed_count"] == 1
    assert data["pending_count"] == 1
    assert data["risk_count"] == 1

def test_local_assistant(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DATA_FILE", tmp_path / "transactions.json")
    main.write_transactions([{"order_id": "TEST-1", "amount": 12.5, "currency": "USD", "status": "COMPLETED", "risk_flag": False}])
    response = client.post("/api/assistant", json={"question": "How many completed payments?"})
    assert response.status_code == 200
    assert "Completed payments: 1" in response.json()["answer"]
