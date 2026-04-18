from decimal import Decimal


BASE_DELIVERY_FEE = Decimal("39.90")
FREE_DELIVERY_THRESHOLD = Decimal("350.00")


def calculate_pricing(items: list[dict]) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = sum(
        Decimal(str(item["unit_price"])) * item["quantity"] for item in items
    )
    delivery_fee = Decimal("0.00") if subtotal >= FREE_DELIVERY_THRESHOLD else BASE_DELIVERY_FEE
    total = subtotal + delivery_fee
    return subtotal, delivery_fee, total
