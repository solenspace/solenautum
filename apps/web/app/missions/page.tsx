import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export default async function MissionsPage() {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  return (
    <main className="p-6">
      <p className="text-sm">Signed in. Mission UI ships in spec 08.</p>
    </main>
  );
}
