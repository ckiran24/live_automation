class FinalFailure(Exception):
    """Configuration, authentication, ambiguous locator, or invalid document."""


class RetryableFailure(Exception):
    """Transient navigation/network/availability failure."""


class LocatorUnavailable(RetryableFailure):
    pass


class AuthenticationFailure(FinalFailure):
    pass
