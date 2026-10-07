import type {
  FieldErrors,
  FieldValues,
  Path,
  UseFormSetFocus,
} from "react-hook-form"

/**
 * Focus the first invalid field of a refused submit, **now**, and nowhere later.
 *
 * react-hook-form's own `shouldFocusError` focuses the error field twice: once synchronously and
 * again from a `setTimeout`. The deferred focus lands after the person (or a test) has already moved
 * on to another field, and what they type next goes into the field that had the error: a refused
 * "Confirm password" pulled the next "Password" keystrokes into itself (the CI flake in
 * `tests/staff.spec.ts`, traced). Every form therefore sets `shouldFocusError: false` and passes
 * this as `handleSubmit`'s `onInvalid`, which focuses once, synchronously.
 *
 * Fields are visited in the order the schema reports them, which is the order each form declares and
 * renders them. `root` is a form-level error with no field to focus.
 */
export const focusFirstError =
  <T extends FieldValues>(setFocus: UseFormSetFocus<T>) =>
  (errors: FieldErrors<T>) => {
    const first = Object.keys(errors).find((name) => name !== "root")
    if (first) setFocus(first as Path<T>)
  }
