import enum


class EventStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MatchStatus(str, enum.Enum):
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    MANUAL = "manual"
    REJECTED = "rejected"


class UserRole(str, enum.Enum):
    USER = "user"
    PHOTOGRAPHER = "photographer"
    ADMIN = "admin"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentTransactionType(str, enum.Enum):
    AUTHORIZATION = "authorization"
    CAPTURE = "capture"
    REFUND = "refund"
    CANCEL = "cancel"


class PaymentTransactionStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class PhotographerStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    SUSPENDED = "suspended"


class PhotoStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class PhotoVisibility(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    HIDDEN = "hidden"


class PhotoTagType(str, enum.Enum):
    RIDER = "rider"
    HORSE = "horse"
    CLASS = "class"
    START_NUMBER = "start_number"
