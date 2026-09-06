import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.business import Business
from app.models.manual import Contact
from app.repositories.leads import DEFAULT_RULESET, LeadFilters
from app.schemas.contacts import (BulkHarvestOut, ContactIn, ContactOut,
                                  ContactUpdate, HarvestOut)
from app.services.contact_export import export_contacts
from app.services.contact_harvest import (harvest_for_business,
                                          harvest_for_filters)
from app.services.contacts import (ContactWouldBeEmptyError,
                                   DuplicateContactError, confirm_contact,
                                   create_contact, delete_contact,
                                   update_contact)

router = APIRouter(tags=["contacts"])


def _business_or_404(db: Session, cid: str) -> Business:
    business = db.query(Business).filter_by(cid=cid).one_or_none()
    if business is None:
        raise HTTPException(status_code=404, detail=f"no such lead: {cid}")
    return business


def _contact_or_404(db: Session, contact_id: int) -> Contact:
    row = db.get(Contact, contact_id)
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"no such contact: {contact_id}")
    return row


@router.get("/contacts/export.csv")
def export_contacts_csv(quadrant: str | None = None,
                        vertical: str | None = None,
                        state: str | None = None,
                        min_fit: int = Query(0, ge=0, le=100),
                        min_pain: int = Query(0, ge=0, le=100),
                        outcome_status: str | None = None,
                        ruleset_version: str = DEFAULT_RULESET,
                        db: Session = Depends(get_db)) -> Response:
    """Takes EVERY filter `GET /leads` takes, and validates them identically.

    FastAPI silently ignores query params an endpoint does not declare, so a
    filter missing here does not fail: it exports the whole contacts table
    under a URL that says otherwise. That is exactly how the leads export
    shipped honouring one filter of five (commit f7b1ef2).

    Declared above the `/contacts/{contact_id}` routes so `export.csv` can
    never be matched as a `{contact_id}` path parameter.
    """
    filters = LeadFilters(quadrant=quadrant, vertical=vertical, state=state,
                          min_fit=min_fit, min_pain=min_pain,
                          outcome_status=outcome_status,
                          ruleset_version=ruleset_version)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "contacts.csv"
        export_contacts(db, filters, path)
        content = path.read_text(encoding="utf-8")
    return Response(
        content=content, media_type="text/csv",
        headers={"content-disposition": 'attachment; filename="contacts.csv"'})


@router.post("/leads/{cid}/contacts", response_model=ContactOut,
             status_code=status.HTTP_201_CREATED)
def create(cid: str, body: ContactIn,
           db: Session = Depends(get_db)) -> Contact:
    business = _business_or_404(db, cid)
    try:
        return create_contact(db, business.id, body)
    except DuplicateContactError:
        # 409, never a 500. This is a normal path: the address the user is
        # typing may already have been harvested.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that email is already a contact for this lead")


@router.put("/contacts/{contact_id}", response_model=ContactOut)
def edit(contact_id: int, body: ContactUpdate,
         db: Session = Depends(get_db)) -> Contact:
    row = _contact_or_404(db, contact_id)
    try:
        return update_contact(db, row, body)
    except DuplicateContactError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that email is already a contact for this lead")
    except ContactWouldBeEmptyError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a contact needs at least a name or an email")


@router.post("/contacts/{contact_id}/confirm", response_model=ContactOut)
def confirm(contact_id: int, db: Session = Depends(get_db)) -> Contact:
    """The export gate. Only a human reaches this."""
    return confirm_contact(db, _contact_or_404(db, contact_id))


@router.delete("/contacts/{contact_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def remove(contact_id: int, db: Session = Depends(get_db)) -> Response:
    delete_contact(db, _contact_or_404(db, contact_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/leads/{cid}/contacts/harvest", response_model=HarvestOut)
def harvest_one(cid: str, db: Session = Depends(get_db)) -> HarvestOut:
    business = _business_or_404(db, cid)
    result = harvest_for_business(db, business.id)
    return HarvestOut(created=result.created, skipped=result.skipped,
                      candidates=result.candidates)


@router.post("/contacts/harvest", response_model=BulkHarvestOut)
def harvest_many(quadrant: str | None = None,
                 vertical: str | None = None,
                 state: str | None = None,
                 min_fit: int = Query(0, ge=0, le=100),
                 min_pain: int = Query(0, ge=0, le=100),
                 outcome_status: str | None = None,
                 ruleset_version: str = DEFAULT_RULESET,
                 db: Session = Depends(get_db)) -> BulkHarvestOut:
    """Takes EVERY filter `GET /leads` takes, and validates them identically.

    FastAPI silently ignores query params an endpoint does not declare, so a
    filter missing here does not fail -- the harvest simply walks every
    business in the database under a URL that says otherwise. That is how the
    leads export shipped honouring one filter of five (commit f7b1ef2), and
    the blast radius here is larger.
    """
    filters = LeadFilters(quadrant=quadrant, vertical=vertical, state=state,
                          min_fit=min_fit, min_pain=min_pain,
                          outcome_status=outcome_status,
                          ruleset_version=ruleset_version)
    result = harvest_for_filters(db, filters)
    return BulkHarvestOut(created=result.created, businesses=result.businesses)
