import { Redirect, useLocalSearchParams } from "expo-router";

/** Universal / App Link target (https://<share host>/s/<id>) → the in-app spark screen. */
export default function InviteLink() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <Redirect href={{ pathname: "/spark/[id]", params: { id } }} />;
}
