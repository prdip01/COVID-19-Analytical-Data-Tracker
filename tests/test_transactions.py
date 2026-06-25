import pytest
from database.connection import get_db
from database.models import CountryMetadata

def test_transaction_rollback_on_exception(clean_db, db_session):
    """Verify that any exception within a get_db() context block causes a complete rollback."""
    # 1. Assert database starts clean
    assert db_session.query(CountryMetadata).count() == 0
    
    # 2. Run a transactional block that inserts a country then raises a RuntimeError
    try:
        with get_db() as session:
            country = CountryMetadata(
                country="Testland",
                population=1000,
                continent="Europe",
                source_file="test.csv"
            )
            session.add(country)
            session.flush()  # Send the insert to the database within transaction
            
            # Assert it is visible in the current transaction session
            assert session.query(CountryMetadata).filter_by(country="Testland").count() == 1
            
            # Raise an exception to trigger rollback
            raise RuntimeError("Simulated transaction crash")
    except RuntimeError:
        pass  # Catch expected test exception
        
    # 3. Open a separate session and verify that the country was not committed
    with get_db() as new_session:
        assert new_session.query(CountryMetadata).filter_by(country="Testland").count() == 0
