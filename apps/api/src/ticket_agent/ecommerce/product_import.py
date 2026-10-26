import csv
import io
from dataclasses import dataclass, field

PRODUCT_IMPORT_COLUMNS = (
    "sku",
    "name",
    "category",
    "brand",
    "price",
    "stock",
    "color",
    "size_range",
    "upper_material",
    "lining_material",
    "sole_material",
    "heel_height_cm",
    "shaft_height_cm",
    "closure",
    "gender",
    "season",
    "origin_country",
    "hs_code",
    "weight_kg",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
)

REQUIRED_IMPORT_COLUMNS = {
    "sku",
    "name",
    "category",
    "brand",
    "price",
    "stock",
    "color",
    "size_range",
    "upper_material",
    "lining_material",
    "sole_material",
    "heel_height_cm",
    "shaft_height_cm",
    "closure",
    "gender",
    "season",
}


class ProductImportParseError(Exception):
    pass


@dataclass
class ParsedProductImportRow:
    row_number: int
    sku: str
    name: str
    category: str
    brand: str
    price: float | None
    attributes: dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ParsedProductImport:
    columns: list[str]
    rows: list[ParsedProductImportRow]


def product_import_template() -> bytes:
    example = {
        "sku": "SNOW-BOOT-001",
        "name": "加绒保暖雪地靴",
        "category": "雪地靴",
        "brand": "示例品牌",
        "price": "129.00",
        "stock": "100",
        "color": "米白色",
        "size_range": "35-40",
        "upper_material": "牛剖层革",
        "lining_material": "短毛绒",
        "sole_material": "橡胶",
        "heel_height_cm": "3",
        "shaft_height_cm": "18",
        "closure": "套筒",
        "gender": "女",
        "season": "秋冬",
        "origin_country": "CN",
        "hs_code": "640399",
        "weight_kg": "0.85",
        "package_length_cm": "32",
        "package_width_cm": "24",
        "package_height_cm": "13",
    }
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRODUCT_IMPORT_COLUMNS)
    writer.writeheader()
    writer.writerow(example)
    return buffer.getvalue().encode("utf-8-sig")


def category_product_import_template(
    *,
    category_name: str,
    required_attributes: list[str],
) -> bytes:
    columns = [
        "sku",
        "name",
        "category",
        "brand",
        "price",
        "stock",
        *required_attributes,
        "origin_country",
        "hs_code",
        "weight_kg",
        "package_length_cm",
        "package_width_cm",
        "package_height_cm",
    ]
    example = {
        "sku": "PRODUCT-001",
        "name": f"{category_name}示例商品",
        "category": category_name,
        "brand": "示例品牌",
        "price": "99.00",
        "stock": "100",
        "origin_country": "CN",
        "weight_kg": "0.5",
        "package_length_cm": "20",
        "package_width_cm": "15",
        "package_height_cm": "10",
    }
    for attribute in required_attributes:
        example[attribute] = f"{attribute}示例值"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerow(example)
    return buffer.getvalue().encode("utf-8-sig")


def parse_product_import_csv(
    data: bytes,
    *,
    existing_skus: set[str],
) -> ParsedProductImport:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProductImportParseError("CSV must use UTF-8 encoding") from exc
    reader = csv.DictReader(io.StringIO(text))
    columns = [column.strip() for column in (reader.fieldnames or [])]
    missing_columns = sorted(REQUIRED_IMPORT_COLUMNS - set(columns))
    if missing_columns:
        raise ProductImportParseError(
            "Missing required columns: " + ", ".join(missing_columns)
        )
    seen_skus = {sku.upper() for sku in existing_skus}
    rows: list[ParsedProductImportRow] = []
    for row_number, raw_row in enumerate(reader, start=2):
        values = {
            str(key).strip(): str(value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        if not any(values.values()):
            continue
        sku = values.get("sku", "")
        name = values.get("name", "")
        errors: list[str] = []
        if not sku:
            errors.append("sku is required")
        elif len(sku) > 100:
            errors.append("sku exceeds 100 characters")
        elif sku.upper() in seen_skus:
            errors.append("sku already exists or is duplicated in this file")
        else:
            seen_skus.add(sku.upper())
        if not name:
            errors.append("name is required")
        elif len(name) > 300:
            errors.append("name exceeds 300 characters")
        for key in REQUIRED_IMPORT_COLUMNS - {"sku", "name"}:
            if not values.get(key):
                errors.append(f"{key} is required")

        price = _optional_float(values.get("price"), "price", errors)
        if price is not None and price < 0:
            errors.append("price must be >= 0")
        stock = _optional_int(values.get("stock"), "stock", errors)
        if stock is not None and stock < 0:
            errors.append("stock must be >= 0")
        heel = _optional_float(
            values.get("heel_height_cm"),
            "heel_height_cm",
            errors,
        )
        shaft = _optional_float(
            values.get("shaft_height_cm"),
            "shaft_height_cm",
            errors,
        )
        weight = _optional_float(values.get("weight_kg"), "weight_kg", errors)
        length = _optional_float(
            values.get("package_length_cm"),
            "package_length_cm",
            errors,
        )
        width = _optional_float(
            values.get("package_width_cm"),
            "package_width_cm",
            errors,
        )
        height = _optional_float(
            values.get("package_height_cm"),
            "package_height_cm",
            errors,
        )
        for label, value in (
            ("heel_height_cm", heel),
            ("shaft_height_cm", shaft),
            ("weight_kg", weight),
            ("package_length_cm", length),
            ("package_width_cm", width),
            ("package_height_cm", height),
        ):
            if value is not None and value <= 0:
                errors.append(f"{label} must be > 0")
        hs_code = values.get("hs_code", "")
        if hs_code and (not hs_code.isdigit() or not 6 <= len(hs_code) <= 10):
            errors.append("hs_code must contain 6 to 10 digits")

        attributes: dict[str, object] = {
            key: values[key]
            for key in (
                "color",
                "size_range",
                "upper_material",
                "lining_material",
                "sole_material",
                "closure",
                "gender",
                "season",
            )
            if values.get(key)
        }
        if stock is not None:
            attributes["stock"] = stock
        if heel is not None:
            attributes["heel_height_cm"] = heel
        if shaft is not None:
            attributes["shaft_height_cm"] = shaft
        for key in ("origin_country", "hs_code"):
            if values.get(key):
                attributes[key] = values[key]
        if weight is not None:
            attributes["weight_kg"] = weight
        if all(value is not None for value in (length, width, height)):
            attributes["package_dimensions_cm"] = {
                "length": length,
                "width": width,
                "height": height,
            }
        rows.append(
            ParsedProductImportRow(
                row_number=row_number,
                sku=sku,
                name=name,
                category=values.get("category", "雪地靴") or "雪地靴",
                brand=values.get("brand", ""),
                price=price,
                attributes=attributes,
                errors=errors,
            )
        )
    if not rows:
        raise ProductImportParseError("CSV contains no product rows")
    return ParsedProductImport(columns=columns, rows=rows)


def parse_category_product_import_csv(
    data: bytes,
    *,
    existing_skus: set[str],
    category_name: str,
    required_attributes: list[str],
) -> ParsedProductImport:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProductImportParseError("CSV must use UTF-8 encoding") from exc
    reader = csv.DictReader(io.StringIO(text))
    columns = [column.strip() for column in (reader.fieldnames or [])]
    required_columns = {
        "sku",
        "name",
        "brand",
        "price",
        "stock",
        *required_attributes,
    }
    missing_columns = sorted(required_columns - set(columns))
    if missing_columns:
        raise ProductImportParseError(
            "Missing required columns: " + ", ".join(missing_columns)
        )
    seen_skus = {sku.upper() for sku in existing_skus}
    rows: list[ParsedProductImportRow] = []
    for row_number, raw_row in enumerate(reader, start=2):
        values = {
            str(key).strip(): str(value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        if not any(values.values()):
            continue
        sku = values.get("sku", "")
        name = values.get("name", "")
        brand = values.get("brand", "")
        errors: list[str] = []
        if not sku:
            errors.append("sku is required")
        elif sku.upper() in seen_skus:
            errors.append("sku already exists or is duplicated in this file")
        else:
            seen_skus.add(sku.upper())
        if not name:
            errors.append("name is required")
        if not brand:
            errors.append("brand is required")
        for attribute in required_attributes:
            if not values.get(attribute):
                errors.append(f"{attribute} is required")
        price = _optional_float(values.get("price"), "price", errors)
        stock = _optional_int(values.get("stock"), "stock", errors)
        if price is not None and price < 0:
            errors.append("price must be >= 0")
        if stock is not None and stock < 0:
            errors.append("stock must be >= 0")
        attributes: dict[str, object] = {
            key: value
            for key, value in values.items()
            if key not in {"sku", "name", "category", "brand", "price", "stock"}
            and value
        }
        if stock is not None:
            attributes["stock"] = stock
        rows.append(
            ParsedProductImportRow(
                row_number=row_number,
                sku=sku,
                name=name,
                category=category_name,
                brand=brand,
                price=price,
                attributes=attributes,
                errors=errors,
            )
        )
    if not rows:
        raise ProductImportParseError("CSV contains no product rows")
    return ParsedProductImport(columns=columns, rows=rows)


def _optional_float(
    value: str | None,
    field_name: str,
    errors: list[str],
) -> float | None:
    if value is None or not value:
        return None
    try:
        return float(value)
    except ValueError:
        errors.append(f"{field_name} must be a number")
        return None


def _optional_int(
    value: str | None,
    field_name: str,
    errors: list[str],
) -> int | None:
    if value is None or not value:
        return None
    try:
        return int(value)
    except ValueError:
        errors.append(f"{field_name} must be an integer")
        return None
