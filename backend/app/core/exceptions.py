class ElevatorNotFoundError(Exception):
    def __init__(self, elevator_id: str) -> None:
        self.elevator_id = elevator_id
        super().__init__(f"Elevator {elevator_id} not found")
