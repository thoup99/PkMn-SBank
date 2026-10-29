"""One-exchange persistence guard for the website's Arceus host mode."""
from pokeldn.app.trade_receipt import write_candidate, write_receipt


class BoundedTrade:
    def __init__(self, candidate, receipt, offer):
        self.candidate = candidate
        self.receipt = receipt
        self.offer = bytes(offer)
        self.incoming = None
        self.phases = set()
        self.completed = False
        self.admitted = False

    def admit(self):
        if self.admitted:
            return False
        self.admitted = True
        return True

    def offered(self, data):
        if self.completed:
            return
        if self.phases and self.incoming != bytes(data):
            raise ValueError("Incoming offer changed during the bounded exchange")
        write_candidate(self.candidate, data)
        self.incoming = bytes(data)

    def phase_sent(self, phase):
        self.phases.add(phase)

    def closed(self):
        if self.completed or self.incoming is None or not {3, 6} <= self.phases:
            return False
        write_receipt(self.receipt, self.incoming, self.offer, game='pla')
        self.completed = True
        return True
