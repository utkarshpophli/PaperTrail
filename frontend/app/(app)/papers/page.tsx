import { redirect } from "next/navigation";

/** The paper list moved to /library; this keeps old links and bookmarks working. */
export default function PapersPage(): never {
  redirect("/library");
}
