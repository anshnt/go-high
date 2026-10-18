import { useParams } from "react-router";
import "../records/records.css";
import { RecordListPage } from "../records/RecordListPage";

// One lazy chunk for every record screen. The route is `/contacts/:id?`, so opening a record keeps the same
// component mounted: the list stays where it was, with its filters and scroll position.
export const ContactsPage = () => <RecordListPage object="contact" />;
export const CompaniesPage = () => <RecordListPage object="company" />;
export const DealsPage = () => <RecordListPage object="deal" />;

/** Custom objects, listed under /objects/:object. */
export function ObjectPage() {
  const { object } = useParams();
  return <RecordListPage object={object ?? ""} />;
}
